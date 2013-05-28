#!/usr/bin/env python
import time 
import datetime
import calendar
import serial
import struct
import os
import sys
import ConfigParser
import sqlite3
import urllib
import urllib2
import ismg
from crontab import CronTab
from serial.tools import list_ports

CONFIGFILE = '/home/pi/.ismgcfg'                   
PVOUTPUT_BATCHSIZE = 30 #30=free, 90=donator

class Gavazzireader_Configuration():
  @staticmethod
  def read(filename):
    config = ConfigParser.RawConfigParser()
    config.read(CONFIGFILE)
    for section in config.sections():
      if section == 'System':
        data_dir = config.get('System', 'Data_Directory')
        try:
          read_cycle = config.get('System', 'read_cycle')
        except:
          read_cycle = None
        try:
          pvoutput_apikey = config.get('System', 'pvoutput_apikey')
        except:
          pvoutput_apikey = None
        inverters = []
      else:
        if not section.startswith('Inverter_'):
          raise ValueError('Unknown section %s in configuration file. Fix it or run "%s --configure"' % (section, sys.argv[0]))
        pv_sysid = ''
        try:
          pv_sysid = config.get(section, 'pvoutput_systemid')
        except:
           print 'no pv'#leave blank
        inverters.append(ismg.ISMGInverter(section[section.find('_')+1:], config.getint(section, 'slave_number'), config.get(section, 'serial_port'), pv_sysid))   
    return Gavazzireader_Configuration(data_dir, inverters, read_cycle, pvoutput_apikey)

  def __init__(self, data_dir, inverters, read_cycle, pvoutput_apikey = None):
    self.data_dir = data_dir
    self.inverters = inverters
    self.read_cycle = read_cycle
    self.pvoutput_apikey = pvoutput_apikey
  
  def get_pvoutput_systemid(self, serial_number):
    for i in self.inverters:
      if i.serial_number() == serial_number:
        return i.pvoutput_systemid
    return None
  

class DatabaseHandler():
  def __init__(self, datadir):
    self.conn = sqlite3.connect(datadir + '/ismgdata.db')
    self.cursor = self.conn.cursor()
    self.cursor.execute('CREATE TABLE IF NOT EXISTS ismgdata ('
        'timestamp "TEXT",'
        'state "TEXT",'
        'error_info "TEXT", '
        'volt_a "REAL",'
        'volt_b "REAL",'
        'volt_c "REAL",'
        'input_power_a "INTEGER", '
        'input_power_b "INTEGER", '
        'input_power_c "INTEGER", '
        'output_voltage "REAL", '
        'output_power "INTEGER", '
        'output_current "REAL", '
        'output_frequency "REAL", '
        'total_output_energy "REAL", '
        'total_input_energy_a "REAL", '
        'total_input_energy_b "REAL", '
        'total_input_energy_c "REAL", '
        'todays_output_minutes "INTEGER", '
        'leakage_current "INTEGER", '
        'heatsink_temp "REAL", '
        'ac_impedance "REAL", '
        'insulation_resistance "REAL", '
        'total_operation_time "TEXT", '
        'relay_on_count "INTEGER", '
        'tripping_voltage "REAL", '
        'tripping_frequcency "REAL", '
        'serial_number "TEXT", ' 
        'version_info "TEXT", '
        'pvoutput_attempts "INTEGER" default 0, '
        'pvoutput_status "INTEGER" default 0);') #0=untransmitted, 1=failed_temporarily, 2=delivered_with_success, 3=failed_permanently
    self.cursor.execute('CREATE INDEX IF NOT EXISTS ismg_timestamp ON ismgdata(timestamp ASC);')
    self.cursor.execute('CREATE INDEX IF NOT EXISTS ismg_serial_number ON ismgdata(serial_number ASC);')
    self.cursor.execute('CREATE INDEX IF NOT EXISTS ismg_pvoutput_status ON ismgdata(pvoutput_status ASC);')
    self.conn.commit()
  def store_reads(self, ismgdataregisterarray):
    self.cursor.executemany('INSERT INTO ismgdata(timestamp, state, error_info, volt_a, volt_b, volt_c, input_power_a, input_power_b, '
                 'input_power_c, output_voltage, output_power,  output_current,  output_frequency,  total_output_energy,  '
                 'total_input_energy_a,  total_input_energy_b,  total_input_energy_c,  todays_output_minutes,  leakage_current,  '
                 'heatsink_temp,  ac_impedance,  insulation_resistance,  total_operation_time,  relay_on_count,  tripping_voltage, '
                 'tripping_frequcency, serial_number, version_info) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', 
                  ismgdataregisterarray)
    self.conn.commit()
    
  def pvoutput_fetch_data_to_transmit(self):
    sql = 'SELECT serial_number, rowid, timestamp, total_output_energy, output_power, pvoutput_attempts from ismgdata WHERE pvoutput_status < 2 AND state = \'Output\' ORDER BY serial_number, timestamp LIMIT %d;' % PVOUTPUT_BATCHSIZE
    rowids = []
    readings=[]
    handling_serial = None
    for record in self.cursor.execute(sql):
      if handling_serial == None:
        handling_serial = record[0]
      if record[0] != handling_serial:
        break;
      rowids.append(record[1])
      utctime = time.strptime(record[2], '%Y-%m-%dZ%H:%M:%S')
      localtime = time.localtime(calendar.timegm(utctime))
      datepart = time.strftime("%Y%m%d", localtime)
      timepart = time.strftime("%H:%M", localtime)
      readings.append('%s,%s,%d,%d' % ( datepart, timepart, 1000 * record[3], record[4]))
    return (handling_serial, rowids, readings)

  def pvoutput_update_status(self, updated_status_code, ids_to_update):
    if len(ids_to_update) == 0:
      return
    updatesql = (len(ids_to_update)-1)*',?'
    updatesql = 'UPDATE ismgdata SET pvoutput_status=%d, pvoutput_attempts=pvoutput_attempts+1 WHERE rowid IN (?%s);' % (updated_status_code, updatesql)
    self.cursor.execute(updatesql, ids_to_update)
    self.conn.commit()

def is_any_inverter_read(inverters):
  for inverter in inverters:
    if inverter.last_read_timestamp != None:
      return True
  return False

  
def send_batch_to_pvoutput():
  success = False
  if conf.pvoutput_apikey == None:
    print 'pvoutput api key not found. Run --configure'
    raise SystemExit()
  (serial, rowids, readings) = db.pvoutput_fetch_data_to_transmit()
  #print 'serial %d' % len(rowids)
  if serial != None:
    sysid = None
    for inverter in conf.inverters:
      if inverter.configured_serial == serial:
        sysid = inverter.pvoutput_systemid
        break
    if sysid == None:
      print 'pvoutput system id not configured for inverter %s. Run --configure' % serial
      raise SystemExit()
      
    httpheaders = {"X-Pvoutput-Apikey" : conf.pvoutput_apikey, "X-Pvoutput-SystemId": sysid}
    httpopener = urllib2.build_opener(urllib2.HTTPHandler(debuglevel=2))
    httpurl = 'http://pvoutput.org/service/r2/addbatchstatus.jsp'
    #print 'sending ', rowids
    req = urllib2.Request(url=httpurl, data='data=%s&c1=1'% ';'.join(readings), headers=httpheaders)
   
    accepted_ids=[]
    rejected_ids=[]
    try:
      responses = []
      httpresponse = urllib2.urlopen(req)      
      responses = httpresponse.read().split(';')
      success = True
    except urllib2.HTTPError, e:
      print 'Reason-hhtp: ', e.reason
      if e.code == 403:
        rejected_ids.extend(rowids)
      print '  : ', e.read()
    except urllib2.URLError, e:
      print 'Reason-url: ', e.reason
      print '  : ', e, e.read()
      rejected_ids.extend(rowids)
    #print responses
    for i in range(len(responses)):
      response = responses[i].split(',')
      #print 'examining ', response
      if response[2] == '1':
        accepted_ids.append(rowids[i])
      else:
        rejected_ids.append(rowids[i])
    #print 'registering rejected:', rejected_ids
    db.pvoutput_update_status(1, rejected_ids)
    #print 'registering accepted:', accepted_ids
    db.pvoutput_update_status(2, accepted_ids)
  else:
    # no data from db to transmit - ignore
    pass
  return success
  

def conf_coalesce(config, section, parameter, default_value):
  config_value = None
  config_value = config.get(section, parameter)
  try:
     config_value = config.get(section, parameter)
  except:
    print sys.exc_info()[0]
    #pass
  if config_value != None:
    return config_value
  return default_value
  
if __name__ == "__main__":
  if len(sys.argv) > 1 and sys.argv[1] == '--configure':
    try:
      conf = Gavazzireader_Configuration.read(CONFIGFILE)
    except:
      conf = Gavazzireader_Configuration('', [], '15', None)
    newconfig = ConfigParser.RawConfigParser()
    newconfig.add_section('System')
    defval = conf.data_dir 
    if defval == '':
      defval = '/home/pi/ismg_data/'
    dp = raw_input('Enter data directory path [%s]: ' % defval)
    if dp == '':
      dp = defval
    newconfig.set('System', 'data_directory', dp)
  
    rc = conf.read_cycle
    if rc == '':
      rc = '15'
    read_cycle = raw_input('Enter minutes between readings (5/10/15/30/60) [%s]: ' % rc)
    if read_cycle == '' or read_cycle not in ('5', '10', '15', '30', '60'): 
      read_cycle = rc
    newconfig.set('System', 'read_cycle', read_cycle)
    
    ak = conf.pvoutput_apikey
    apikey = raw_input('Enter API key for pvoutput.org [%s] (\'-\' to remove): ' % ak)
    if apikey != '-':
      if apikey == '':
        apikey = ak
      newconfig.set('System', 'pvoutput_apikey', apikey)

    inverters_alive = ismg.ISMGFinder.scan()
    for conf_inv in inverters_alive:
      #try:
        conf_inv.perform_read() #need to get serial for configuration
        inv_serial = conf_inv.serial_number()
        config_section_name = 'Inverter_%s' % inv_serial
        newconfig.add_section(config_section_name)
        oldsysid = conf.get_pvoutput_systemid(inv_serial)
        if apikey != '':
          pvsysid = raw_input('pvoutput.org system_id for inverter: Serial=%s, Slave_id=%s, Port=%s [%s] (\'-\' to remove): ' % (conf_inv.serial_number(), conf_inv.serial_port, conf_inv.slave_number, oldsysid))
          if pvsysid != '-':
            if pvsysid == '':
              pvsysid = oldsysid
            if pvsysid != None:
              newconfig.set(config_section_name, 'pvoutput_systemid', pvsysid)
        newconfig.set(config_section_name, 'serial_port', conf_inv.serial_port)
        newconfig.set(config_section_name, 'slave_number', conf_inv.slave_number)
      #except:
      #  print sys.exc_info()[0]
      #  continue
    if raw_input('Really write configuration file with %d inverters? (\'y\' to write): ' % len(inverters_alive)) == 'y':
      with open(CONFIGFILE, 'wb') as configfile:                                   
        newconfig.write(configfile)
    raise SystemExit()


  
  if not os.path.exists(CONFIGFILE):
    raise SystemExit('Configuration does not exist. Run "python %s --configure" to generate' % sys.argv[0])
  conf = Gavazzireader_Configuration.read(CONFIGFILE)
  if not os.path.exists(conf.data_dir):
    os.mkdir(conf.data_directory)
  db = DatabaseHandler(conf.data_dir)

  #for inve in conf.inverters:
  #  print "found %s on %s "% (inve.slave_number, inve.serial_port)

  for inverter in conf.inverters:  
    try:
      inverter.perform_read()
    except:
      pass

  
  if len(sys.argv) == 0 and not is_any_inverter_read(conf.inverters):
    # nothing read from inverters - perhaps the sun is not up - quit silently
    raise SystemExit()
  
  if len(sys.argv) > 1:
    if sys.argv[1] == '--cron':
      job_comment = 'gavazzireader_identifier_comment__do_not_delete'
      if conf.read_cycle == None or conf.read_cycle not in ('5', '10', '15', '30'):
        raise SystemExit('No read cycle defined (%s). Configure with --configure' % conf.read_cycle)
      ct = CronTab()
      existingjob = ct.find_comment(job_comment)
      if len(existingjob) > 0:
        for ej in existingjob:
          ct.remove(ej)
      newjob = ct.new(command='%s %s'%(sys.executable, sys.argv[0]),comment=job_comment)
      newjob.minute.every(conf.read_cycle)
      ct.write()
      raise SystemExit()
      
    elif sys.argv[1] == '--pvoutputonly':
      send_batch_to_pvoutput()
      raise SystemExit()
    elif sys.argv[1] != None:
      print 'Unknown argument: ', sys.argv[1:]

#  if not os.path.exists(CONFIGFILE):
#    raise SystemExit('Configuration does not exist. Run "python %s --configure" to generate' % sys.argv[0])
  
  data_to_store = []
  for inverter in conf.inverters:
    if inverter.last_read_timestamp == None:
      print 'Skipping unread inverter', inverter.slave_number 
    else:
      filename = '%s_%s.csv' % (time.strftime('%Y%m%d', inverter.last_read_timestamp), inverter.serial_number())
      file = open(conf.data_dir + '/' + filename, 'a')
      inverter.write_parameters_to_file(file)
      file.close()
      data_to_store.append((time.strftime('%Y-%m-%dZ%H:%M:%S', inverter.last_read_timestamp), inverter.state(), inverter.error_info(), inverter.voltage_a(),
                   inverter.voltage_b(),  inverter.voltage_c(),  inverter.input_power_a(),  inverter.input_power_b(), inverter.input_power_c(), 
                   inverter.output_voltage(), inverter.output_power(), inverter.output_current(), inverter.output_frequency(), inverter.total_output_energy(),
                   inverter.total_input_energy_a(), inverter.total_input_energy_b(), inverter.total_input_energy_c(), inverter.todays_output_minutes(), 
                   inverter.leakage_current(), inverter.heatsink_temp(), inverter.ac_impedance(), inverter.insulation_resistance(), inverter.total_operation_time(),
                   inverter.relay_on_count(), inverter.tripping_voltage(), inverter.tripping_frequcency(), inverter.serial_number(), inverter.version_info()))

  db.store_reads(data_to_store)

  send_more = True
  while send_more:
    #print 'sending'
    send_more = send_batch_to_pvoutput()
    time.sleep(5)