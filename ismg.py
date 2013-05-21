import time 
import datetime
import calendar
import serial
import struct
from serial.tools import list_ports

class ISMGInverter():
  check_cmd = [3,  1,  9,  0,  3]
  read_cmds = {181: [3, 0, 181, 0, 15],
               196: [3, 0, 196, 0, 15],
               211: [3, 0, 211, 0, 5],
               265: [3, 1,   9, 0, 6]}
  
  def __init__(self, configured_serial, slave_number, serial_port, pvoutput_systemid = ''):
    self.configured_serial = configured_serial
    self.slave_number = slave_number
    self.serial_port = serial_port
    self.last_read_timestamp = None
    self.pvoutput_systemid = pvoutput_systemid
    self.registers = {
     #block1
       181:ISMGParameter('State'                                           ),
       182:ISMGParameter('Error_Code1'                                     ),
       183:ISMGParameter('Error_Code2'                                     ),
       184:ISMGParameter('Error_Code3'                                     ),
       185:ISMGParameter('Error_Code4'                                     ),
       186:ISMGParameter('Vpv input voltageA',                '0.1V'       ),
       187:ISMGParameter('Vpv input voltage B',               '0.1V'       ),
       188:ISMGParameter('Vpv input voltage C',               ' 0.1V'      ),
       189:ISMGParameter('Pv input powerA',                   '1W'         ),
       190:ISMGParameter('Pv input power B',                  '1W'         ),
       191:ISMGParameter('Pv input power C',                  '1W'         ),
       192:ISMGParameter('Output voltage',                    '0.1V'       ),
       193:ISMGParameter('Output power',                      '1W'         ),
       194:ISMGParameter('Output current',                    '0.1A'       ),
       195:ISMGParameter('Output frequency',                  '0.01Hz'     ),
       # block2
       196:ISMGParameter('Total output energy high word',     '1000KWHr'   ),
       197:ISMGParameter('Total output energy low word',      '0.1KWHr'    ),
       198:ISMGParameter('PvAtotal input energy high word',   '1000KWHr'   ),
       199:ISMGParameter('PvAtotal input energy low word',    '0.1KWHr'    ),
       200:ISMGParameter('Pv B total input energy high word', '1000KWHr'   ),
       201:ISMGParameter('Pv B total input energy low word',  '0.1KWHr'    ),
       202:ISMGParameter('Pv C total input energy high word', '1000KWHr'   ),
       203:ISMGParameter('Pv C total input energy low word',  '0.1KWHr'    ),
       204:ISMGParameter('Output time today',                 '1/2048 Hr'  ),
       205:ISMGParameter('Leakage current',                   '1mA'        ),
       206:ISMGParameter('Heatsink temperature',              '0.1 C'      ),
       207:ISMGParameter('AC impedance',                      '0.01 Ohm'   ),
       208:ISMGParameter('Insulation resistance',             '0.01 MOhm'  ),
       209:ISMGParameter('Total output hours',                'Hr'         ),
       210:ISMGParameter('Total output minutes',              'Min'        ),
     # block3
       211:ISMGParameter('Total output seconds',              'Sec'        ),
       212:ISMGParameter('Relay turn on times, high word',    '65536 times'),
       213:ISMGParameter('Relay turn on times, low word',     'times'      ),
       214:ISMGParameter('The voltage at tripping',           '0.1V'       ),
       215:ISMGParameter('The frequency at tripping',         '0.01Hz'     ),
     # block4
       265:ISMGParameter('Model name - 330,380, or 460'                    ),
       266:ISMGParameter('Serial number high word - 0~9999(YYMM)'          ),
       267:ISMGParameter('Serial number low word - 0~9999'                 ),
       268:ISMGParameter('DEVICE_VER - Hardware Version'                   ),
       269:ISMGParameter('Version_SEQU - DSP1 Version'                     ),
       270:ISMGParameter('Version_CURR - DSP2 Version'                     )
    }
   
  def crconebyte(self, initial_crc, the_byte):
    reg = initial_crc ^ the_byte # 1 xor byte vs register
    for i in range(8):           # repeat 8 times:
      if reg % 2 == 1:           # if lsb = 1 xor a001 - next byte
        reg = reg >> 1      
        reg = reg ^ 0xA001  
      else:
        reg = reg >> 1
    return reg
  
  def modbuscrc16(self, array_of_bytes):  
    crc = 0xFFFF
    for b in array_of_bytes:
      crc = self.crconebyte(crc,b)
    return ((crc & 0x00FF), ((crc >> 8) & 0x00FF)) #=(crc_hi, crc_lo)
  
  def transmit_and_receive(self, sername, bytes):
    serialport = serial.Serial( port=sername, baudrate=9600, bytesize=8, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE)
    serialport.write(bytes)
    time.sleep(0.1);
    recv = bytearray()   
    while serialport.inWaiting() > 0:
      recv.append(serialport.read(1))
    serialport.close()
    bytes_received = len(recv)
    if bytes_received==0:
      raise TypeError('No response received')
    else:
      return self.extract_received_bytes(recv)

  def extract_received_bytes(self, received_bytes):
    if len(received_bytes) == 0:
      return received_bytes	
    if received_bytes[0] != 0x0A:
      raise  TypeError('Start delimiter incorrect') 
    if received_bytes[-1] != 0x0D:
      raise  TypeError('End delimiter incorrect')
    data_bytes = received_bytes[1:-3]
    (crc_hi, crc_lo) = self.modbuscrc16(data_bytes)
    if crc_hi != received_bytes[-3] or crc_lo != received_bytes[-2]:
      raise TypeError('CRC value not expected')
    if received_bytes[2] != 3:
      raise TypeError('Not a result from a read-command')
    if received_bytes[3] != len(received_bytes) - 7: #delimiter, slave, function, bytecount + crchi, crclo, delimiter
      raise TypeError('Byte count field does not match received number of bytes')
    #print "Data: ",
    #for x in data_bytes:
    #  print "%d" % x,
    return (received_bytes[1], received_bytes[4:-3])

  def add_crc_and_delimit(self, bytevalues):
    (crchi, crclo) = self.modbuscrc16(bytevalues)
    #prepend start-byte (0x0A), CRC-bytes and stop-byte (0x0D)
    tmpp = [0x0A]
    tmpp.extend(bytevalues)
    tmpp.append(crchi)
    tmpp.append(crclo)
    tmpp.append(0x0D)
    return struct.pack('>%dB' % len(tmpp), *tmpp)

  def perform_read(self):
    self.last_read_timestamp = None
    for (first_param, cmdbytes) in ISMGInverter.read_cmds.iteritems():
      fullcmd = [self.slave_number]
      fullcmd.extend(cmdbytes[:])
      (recv_slave, recv_bytes) = self.transmit_and_receive(self.serial_port, self.add_crc_and_delimit(fullcmd))
      if recv_slave != self.slave_number:
        raise TypeError('Received response from slave %d when communicating with slave %d') %(recv_slave, self.slave_number)
      for p_idx in range(len(recv_bytes)/2):
        self.registers[first_param+p_idx].parameter_value = (recv_bytes[p_idx * 2] << 8) + recv_bytes[p_idx * 2 + 1]
    self.last_read_timestamp = time.gmtime()

  def responds(self):
    fullcmd = [self.slave_number]
    fullcmd.extend(ISMGInverter.check_cmd[:])
    try:
      (recv_slave, recv_bytes) = self.transmit_and_receive(self.serial_port, self.add_crc_and_delimit(fullcmd))
      if recv_slave != self.slave_number:
        return False
      return True
    except:
      return False	

  def state(self):
    return {10:'Initialize', 11:'Utility frequency detect', 20:'Renew(restart)', 30:'Wait', 
     40:'Monitoring', 50:'Output', 60:'Fault', 61:'Idle', 70:'Default', 80:'Stop', 90:'Calibrate'}[self.registers[181].parameter_value]
  
  def error_info(self):
    return '%d-%d-%d-%d' % (self.registers[182].parameter_value, self.registers[183].parameter_value, self.registers[184].parameter_value, self.registers[185].parameter_value)
  
  def voltage_a(self):
    return 0.1 * self.registers[186].parameter_value  

  def voltage_b(self):
    return 0.1 * self.registers[187].parameter_value
 
  def voltage_c(self):
    return 0.1 * self.registers[188].parameter_value
  
  def input_power_a(self):
    return self.registers[189].parameter_value

  def input_power_b(self):
    return self.registers[190].parameter_value
    
  def input_power_c(self):
    return self.registers[191].parameter_value
  
  def output_voltage(self):
    return 0.1 * self.registers[192].parameter_value
   
  def output_power(self):
    return self.registers[193].parameter_value
  
  def output_current(self):
    return 0.1 * self.registers[194].parameter_value
  
  def output_frequency(self):
    return 0.01 * self.registers[195].parameter_value
    
  def total_output_energy(self):
    return self.registers[196].parameter_value * 1000 + self.registers[197].parameter_value * 0.1

  def total_input_energy_a(self):
    return self.registers[198].parameter_value * 1000 + self.registers[199].parameter_value * 0.1

  def total_input_energy_b(self):
    return self.registers[200].parameter_value * 1000 + self.registers[201].parameter_value * 0.1

  def total_input_energy_c(self):
    return self.registers[202].parameter_value * 1000 + self.registers[203].parameter_value * 0.1

  def todays_output_minutes(self):
    return int(self.registers[204].parameter_value / 2048 * 60)

  def leakage_current(self):
    return self.registers[205].parameter_value

  def heatsink_temp(self):
    return 0.1 * self.registers[206].parameter_value

  def ac_impedance(self):
    return 0.01 * self.registers[207].parameter_value
  
  def insulation_resistance(self):
    return 0.01 * self.registers[208].parameter_value
    
  def total_operation_time(self):
    return '%d:%2d:%2d' % (self.registers[209].parameter_value, self.registers[210].parameter_value, self.registers[211].parameter_value)

  def relay_on_count(self):
    return 65536 * self.registers[212].parameter_value + self.registers[213].parameter_value

  def tripping_voltage(self):
    return 0.1 * self.registers[214].parameter_value

  def tripping_frequcency(self):
    return 0.01 * self.registers[215].parameter_value

  def serial_number(self):
    return '%03d%04d%04d' % (self.registers[265].parameter_value, self.registers[266].parameter_value, self.registers[267].parameter_value)
    
  def version_info(self):
    return '%d-%d-%d' % (self.registers[268].parameter_value, self.registers[269].parameter_value, self.registers[270].parameter_value)
      
  def write_parameters_to_file(self, opened_file_handle):
    opened_file_handle.write('%s;%s;%s;%.1f;%.1f;%.1f;%d;%d;%d;%.1f;%d;%.1f;%.2f;%.1f;%.1f;%.1f;%.1f;%d;%d;%.1f;%.2f;%.2f;%s;%d;%.1f;%.2f;%s;%s\n' % (
      time.strftime('%Y-%m-%dZ%H:%M:%S', self.last_read_timestamp),
      self.state(),
      self.error_info(), 
      self.voltage_a(), 
      self.voltage_b(), 
      self.voltage_c(), 
      self.input_power_a(), 
      self.input_power_b(), 
      self.input_power_c(), 
      self.output_voltage(), 
      self.output_power(), 
      self.output_current(), 
      self.output_frequency(), 
      self.total_output_energy(), 
      self.total_input_energy_a(), 
      self.total_input_energy_b(), 
      self.total_input_energy_c(), 
      self.todays_output_minutes(), 
      self.leakage_current(), 
      self.heatsink_temp(), 
      self.ac_impedance(), 
      self.insulation_resistance(), 
      self.total_operation_time(), 
      self.relay_on_count(), 
      self.tripping_voltage(), 
      self.tripping_frequcency(), 
      self.serial_number(), 
      self.version_info()))

  def dump_parameters(self):
    print "Slave %d read at %s" % (self.slave_number, datetime.datetime.fromtimestamp(self.last_read_timestamp).strftime('%Y-%m-%d %H:%M:%S'))
    for regno, register in self.registers.iteritems():
      if register.parameter_value != None:
        print ' parameter (%d) "%s" => %d [%s]' % (regno, register.name, register.parameter_value, register.unit)
      #else:
      #  print ' %d not set'% regno


class ISMGParameter():
  def __init__(self,  name, unit = None):
    self.name = name
    self.unit = unit
    self.parameter_value = None


class ISMGFinder():
  @staticmethod
  def scan():
    inverters = []
    for serial_port_info in list_ports.comports():
      for slave in range(256):
        print 'checking %s-%03d' % (serial_port_info[0], slave)
        inverter_to_check = ISMGInverter('', slave, serial_port_info[0])
        if inverter_to_check.responds():
          inverters.append(inverter_to_check)
    return inverters

if __name__ == "__main__":
  print 'Don\'t run this...'