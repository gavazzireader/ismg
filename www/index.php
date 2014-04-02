<?php
    function getPDO() {
      $dbhost='127.0.0.1';
      $dbname='ismgdata';
      $dbuser='gavazzireader';
      $dbpass='ismg';
      return new PDO("mysql:host=$dbhost;dbname=$dbname", $dbuser, $dbpass, array( PDO::ATTR_PERSISTENT => false));
    }

    function get_year_production_summary() {
        $db = getPDO();
        $sqltxt = "select serial_number, year, MAX(this_years_output_energy) AS year_output FROM " .
                    "(SELECT reading.serial_number, SUBSTR(timestamp, 1, 4) AS year, reading.total_output_energy - coalesce(yearend.max_output_energy, 0) as this_years_output_energy " .
                    "FROM ismgdata reading LEFT JOIN (SELECT serial_number, SUBSTR(timestamp, 1, 4) AS year, MAX(total_output_energy) AS max_output_energy " .
                    "FROM ismgdata GROUP BY serial_number, SUBSTR(timestamp, 1, 4)) yearend " . 
                    "ON SUBSTR(reading.timestamp, 1, 4) = (yearend.year + 1) AND reading.serial_number = yearend.serial_number " .
                    ") ytdvalues " .
                    "GROUP BY year, serial_number " .
                    "ORDER BY year, serial_number;";
        $resultset = $db->query($sqltxt);
        $resultrows = $resultset->fetchAll();
        $years = array();
        foreach($resultrows as $row) {
            $years[$row['year']][$row['serial_number']] = $row['year_output'];
        }
        return json_encode($years);
    }

    function get_lifetime_production() {
        $db = getPDO();
        $sqltxt = "SELECT serial_number, MAX(total_output_energy) AS lifetime_production FROM ismgdata GROUP BY serial_number;";
        $resultset = $db->query($sqltxt);
        $resultrows = $resultset->fetchAll();
        $inverters = array();
        foreach($resultrows as $row) {
            $inverters[$row['serial_number']] = $row['lifetime_production'];
        }
        return json_encode($inverters);
    }
    
    
    function get_day_production_summary() {
        $db = getPDO();
        $sqltxt= "SELECT dayo, serial_number, MAX(total_output_energy) - MIN(total_output_energy) production FROM " .
                    "(SELECT SUBSTR(timestamp, 1, 10) dayo, serial_number, total_output_energy FROM ismgdata) bases ". 
                    "WHERE dayo > SUBSTR(now() - INTERVAL 30 DAY, 1, 10) " .
                    "GROUP BY serial_number, dayo " .
                    "ORDER BY dayo, serial_number;";
        $resultset = $db->query($sqltxt);
        $resultrows = $resultset->fetchAll();
        $days = array();
        foreach($resultrows as $row) {
            $days[$row['dayo']][$row['serial_number']] = $row['production'];
        }
        $jsonrows = array();
        $inverters = array();
        $graphcolumn = 0;

        $labels = [];
        $axes = [];
        $first_day = reset($days);
        foreach(array_keys($first_day) as $serial) {
            $labels[] = '{"label":"' . substr($serial, -3) . ' [kWh]", "type":"number"}';
            $axes[] = " 0";
        }
        $labels[] = '{"label":"Total [kWh]", "type":"number"}';
        $axes[] = " 1";
        
        foreach(array_keys($days) as $day) {
            $inv_values = [];
            $day_sum = 0;
            foreach(array_keys($days[$day]) as $inverter) {
                $inv_values[$inverter] = '{"v": ' . $days[$day][$inverter] . ', "f":"' . number_format($days[$day][$inverter], 1) . ' kWh(('.substr($inverter, -3).')"} ';
                $day_sum += $days[$day][$inverter];
            }
            $values[] = '{"c":[{"v":"Date(' . substr($day, 0, 4) . ',' . (substr($day, 5, 2)-1) . ',' .substr($day, 8,2) . ')", "f":"' . $day . '"}, ' . join($inv_values, ',') . ', {"v":' . $day_sum . ', "f":"' . number_format($day_sum, 1) . ' kWh(Total)"}]}';
        }
        ;

        return '{"cols": [{"label":"Time", "type":"date"},' . join($labels, ',') . '], "rows": [' . join($values, ',') .'], "p": {"axisInfo": [' . join($axes, ",") . ']}}';
    }
    
    function get_month_production_summary() {
        $db = getPDO();
        $sqltxt= "SELECT datestamp, serial_number, MAX(total_output_energy) - MIN(total_output_energy) production FROM " .
                    "(SELECT SUBSTR(timestamp, 1, 7) datestamp, serial_number, total_output_energy FROM ismgdata) bases ". 
                    "GROUP BY serial_number, datestamp " .
                    "ORDER BY datestamp, serial_number;";
        $resultset = $db->query($sqltxt);
        $resultrows = $resultset->fetchAll();
        $production_summary = [];
        foreach($resultrows as $row) {
            $yr = substr($row['datestamp'], 0, 4);
            $mon = substr($row['datestamp'], 5, 2);
            $production_summary[$mon][$yr][$row['serial_number']] = $row['production'];
        }
        //$production_summary['06'][2012]['33012100172'] = 930;
        ksort($production_summary);
        foreach($production_summary as $monthname) {
            ksort($monthname);
            foreach($monthname as $serial) {
                ksort($serial);
            }
        }
        $year_columns = [];
        // for now, ignore the inverter subtotals
        $first_year = 3000;
        $last_year = 0;
        foreach($production_summary as $years_array) {
            foreach(array_keys($years_array) as $yearname) {
                if($yearname < $first_year) { $first_year = $yearname; }
                if($yearname > $last_year) { $last_year = $yearname; }
            }
        }
        $year_columns[] = '{"label":"Month", "type":"string"}';
        for($year = $first_year; $year <= $last_year; $year++) {
            $year_columns[] = '{"label":"' . $year .'", "type":"number"}';
        }
        $monthnames = [ 1=>'Jan', 2=>'Feb', 3=>'Mar', 4=>'Apr', 5=>'May', 6=>'Jun', 7=>'Jul', 8=>'Aug', 9=>'Sep', 10=>'Oct', 11=>'Nov', 12=>'Dec'];
        // expected result:
        // month, 2012, 2013 
        // 'january', 50, 51
        // 'february', 54, 55
        // ...
        $dataentries = [];
        $datarows = [];
        foreach(array_keys($monthnames) as $monthno) {
            $dataentries[] = '{"v":"' . $monthnames[intval($monthno)] . '"}';
            for($year = $first_year; $year <= $last_year; $year++) {
                $year_total_production = 0;
                if(array_key_exists($year, $production_summary[sprintf("%02d", $monthno)])) {
                    foreach($production_summary[sprintf("%02d", $monthno)][$year] as $inverter_year_production) {
                        $year_total_production += $inverter_year_production;
                    }
                }
                $dataentries[] = '{"v":' . $year_total_production . ', "f":"' . number_format($year_total_production, 1) . ' kWh"}';
            }
            $datarows[] = '{"c":[' . join($dataentries, ', ') . ']}';
            $dataentries = [];
        }
        return '{"cols": [' . join($year_columns, ', ') . '], "rows": [' . join($datarows, ', ') .']}';
    }
  
   
    
    function get_output_power() {
        $db = getPDO();
             $sqltxt = "SELECT reading.timestamp, reading.serial_number, reading.input_power_a, reading.input_power_b, reading.input_power_c, reading.output_power, ". 
                        //"reading.total_output_energy, " . "reading.total_input_energy_a, reading.total_input_energy_b, reading.total_input_energy_c, ".
                        "reading.leakage_current, reading.heatsink_temp, reading.insulation_resistance, " .
                        "reading.total_input_energy_a - daystart.min_energy_a AS todays_input_energy_a, reading.total_input_energy_b - daystart.min_energy_b AS todays_input_energy_b, " .
                        "reading.total_input_energy_c - daystart.min_energy_c AS todays_input_energy_c, reading.total_output_energy - daystart.min_output_energy as todays_output_energy " .
                    "FROM ismgdata reading JOIN (SELECT serial_number, SUBSTR(timestamp, 1, 10) AS day, MIN(total_output_energy) AS min_output_energy, " .
                    "MIN(total_input_energy_a) AS min_energy_a, MIN(total_input_energy_b) AS min_energy_b, MIN(total_input_energy_c) AS min_energy_c FROM ismgdata " .
                    "GROUP BY serial_number, SUBSTR(timestamp, 1, 10)) daystart ON SUBSTR(reading.timestamp, 1, 10) = daystart.day AND reading.serial_number = daystart.serial_number " .
                    "ORDER BY timestamp DESC LIMIT 200;";
//        $sqltxt = "SELECT reading.timestamp, reading.serial_number, reading.leakage_current, reading.heatsink_temp, reading.insulation_resistance " .
//                    "FROM ismgdata ORDER BY timestamp DESC LIMIT 100;";
        $resultset = $db->query($sqltxt);
        $resultrows = $resultset->fetchAll();
        $jsonrows = array();
        $inverters = array();
        $graphcolumn = 0;
        
        //determine the number of inverters
        foreach($resultrows as $row) {
          if(!array_key_exists($row['serial_number'], $inverters)) {
            $inverters[$row['serial_number']] = $graphcolumn++;
          }
        }
        
        $jsonseries = [];
        $axes = [];
        foreach(array_keys($inverters) as $serial) {
            $jsonseries[$inverters[$serial]] = '{"label":"' . substr($serial, -3) . '-A [W]", "type":"number"},' .
                                               '{"label":"' . substr($serial, -3) . '-B [W]", "type":"number"},' .
                                               '{"label":"' . substr($serial, -3) . '-C [W]", "type":"number"},' . 
                                               '{"label":"' . substr($serial, -3) . '-Out [W]", "type":"number"},' .
                                               '{"label":"' . substr($serial, -3) . '-Out [Wh]", "type":"number"},' .
                                               '{"label":"' . substr($serial, -3) . '-A [Wh]", "type":"number"},' . 
                                               '{"label":"' . substr($serial, -3) . '-B [Wh]", "type":"number"},' .
                                               '{"label":"' . substr($serial, -3) . '-C [Wh]", "type":"number"}';
            $axes[] = " 0, 0, 0, 0, 1, 1, 1, 1";
        }

 //                                              '{"label":"' . $serial . ' Leakage Current", "type":"number"},' .
 //                                              '{"label":"' . $serial . ' Temperature", "type":"number"},' .
 //                                              '{"label":"' . $serial . ' Insulation Resistance", "type":"number"},' .
 //                                              '{"label":"' . $serial . ' AC Energy (Day)", "type":"number"},' . 
        foreach($resultrows as $dbrow) {
            $ts = DateTime::createFromFormat('Y-m-dG:ie', substr($dbrow['timestamp'],0,10) . substr($dbrow['timestamp'], 11, 5) . 'UTC');
            $ts->setTimezone(new DateTimeZone(date_default_timezone_get())); //move to local time zone for formatting purposes
            
            $novalue = substr(str_repeat('{"v":null, "f":null},', 8), 0, -1);
            $graphcol = [];
            for($i=0; $i<count($inverters); $i++) {
              $graphcol[$i] = $novalue;
            }
            $graphcol[$inverters[$dbrow['serial_number']]] = 
            '{"v": ' . $dbrow['input_power_a']. ', "f":"' . $dbrow['input_power_a'] . ' W"},' .
            '{"v": ' . $dbrow['input_power_b']. ', "f":"' . $dbrow['input_power_b'] . ' W"},' .
            '{"v": ' . $dbrow['input_power_c']. ', "f":"' . $dbrow['input_power_c'] . ' W"},' .
            '{"v": ' . $dbrow['output_power']. ', "f":"' . $dbrow['output_power'] . ' W"},' .
            '{"v": ' . $dbrow['todays_output_energy'] . ', "f":"' . $dbrow['todays_output_energy'] . ' Wh"},' .
            '{"v": ' . $dbrow['todays_input_energy_a']. ', "f":"' . $dbrow['todays_input_energy_a'] . ' Wh"},' .
            '{"v": ' . $dbrow['todays_input_energy_b']. ', "f":"' . $dbrow['todays_input_energy_b'] . ' Wh"},' .
            '{"v": ' . $dbrow['todays_input_energy_c']. ', "f":"' . $dbrow['todays_input_energy_c'] . ' Wh"} ';
            $jsonrows[] = '{"c":[{"v":"Date(' . $ts->format('Y,') . ($ts->format('m')-1) . $ts->format(',d,H,i,s') . ')", "f":"' . $ts->format('Y-m-d H:i:s') . '"}, ' . join($graphcol, ',') .']}';
            
        }
//            '{"v": ' . $dbrow['total_output_energy']. ', "f":"' . $dbrow['total_output_energy'] . ' Wh"},' .
//            '{"v": ' . $dbrow['total_input_energy_a']. ', "f":"' . $dbrow['total_input_energy_a'] . ' Wh"},' .
//            '{"v": ' . $dbrow['total_input_energy_b']. ', "f":"' . $dbrow['total_input_energy_b'] . ' Wh"},' .
//            '{"v": ' . $dbrow['total_input_energy_c']. ', "f":"' . $dbrow['total_input_energy_c'] . ' Wh"},' .

//            '{"v": ' . $dbrow['leakage_current']. ', "f":"' . $dbrow['leakage_current'] . ' mA"},' .
//            '{"v": ' . $dbrow['heatsink_temp']. ', "f":"' . $dbrow['heatsink_temp'] . ' C"},' .
//            '{"v": ' . $dbrow['insulation_resistance']. ', "f":"' . $dbrow['insulation_resistance'] . ' * 10k Ohm"},' .
        return '{"cols": [{"label":"Time", "type":"datetime"},' . join($jsonseries, ',') . '], "rows": [' . join($jsonrows, ', ') .'], "p": {"axisInfo": [' . join($axes, ",") . ']}}';
    }

    if(array_key_exists('get_data', $_REQUEST)) {
        switch($_REQUEST['get_data']) {
            case 'output_power':
                $json = get_output_power();
                header('Content-Type: application/json');
                echo $json;
                break;
            case 'year_summary':
                header('Content-Type: application/json');
                echo get_year_production_summary();
                break;
            case 'day_summary':
                header('Content-Type: application/json');
                echo get_day_production_summary();
                break;
            case 'month_summary':
                header('Content-Type: application/json');
                echo get_month_production_summary();
                break;
            case 'tjek':
                echo substr(str_repeat('oh,',1),0, -1) . 'is ok';
                break;
            default: 
                print "Bad move";
        }
        exit();
    }
?>
<html>
    <head>
        <link rel="stylesheet" type="text/css" href="gavazzistyle.css">
        <script type="text/javascript" src="https://www.google.com/jsapi"></script>
        <script type="text/javascript" src="http://code.jquery.com/jquery-1.10.1.min.js"></script>
        <script type="text/javascript">
            var thechart;
            function showDaySummary() {
                var daychart = null;
                $.ajax({
                    url: '/index.php',
                    type: 'POST',
                    data: {
                        get_data: 'day_summary'
                    },
                    dataType: 'json',
                    success: function (jd) {
                        var data = new google.visualization.DataTable(jd);
                        //var table = new google.visualization.Table(document.getElementById('day_summary_table'));
                        //table.draw(data, {showRowNumber: true});
                        daychart = new google.visualization.LineChart(document.getElementById('day_summary_graph'));
                        var seriesaxisarray = [];
                        console.log('1');
                        for(i=0; i<jd.p.axisInfo.length; i++) {
                            console.log('1½');
                            seriesaxisarray[i] = { targetAxisIndex: jd.p.axisInfo[i] }
                        }
                        //console.log(seriesaxisarray);
                        var dayview = new google.visualization.DataView(data);
                        console.log('2');
                        var dayoptions = {width: 800, height: 500, interpolateNulls:true, hAxis: {format: 'yyyy-MM-dd', slantedText: true}, legend: { position: 'right'}, series: seriesaxisarray, vAxes:{1:{title:'Total',textStyle:{color: 'blue'}}}};
                        console.log('setting view');
                        dayview.setColumns([0, jd.p.axisInfo.length]);
                        console.log('view set');
                        daychart.draw(dayview, dayoptions);
                    },
                    error: function (e) {
                        console.log('Problem!');
                        console.log(e);
                        console.log(e.getAllResponseHeaders());
                    }
                });
                
 //           google.visualization.events.addListener(daychart, 'select', function () {
 //       var sel = chart.getSelection();
 //       // if selection length is 0, we deselected an element
 //       if (sel.length > 0) {
 //           // if row is undefined, we clicked on the legend
 //           if (typeof sel[0].row === 'undefined') {
 //               var col = sel[0].column;
 //               if (columns[col] == col) {
 //                   // hide the data series
 //                   columns[col] = {
 //                       label: data.getColumnLabel(col),
 //                       type: data.getColumnType(col),
 //                       calc: function () {
 //                           return null;
 //                       }
 //                   };
 //                   
 //                   // grey out the legend entry
 //                   series[col - 1].color = '#CCCCCC';
 //               }
 //               else {
 //                   // show the data series
 //                   columns[col] = col;
 //                   series[col - 1].color = null;
 //               }
 //               var view = new google.visualization.DataView(data);
 //               view.setColumns(columns);
 //               chart.draw(view, options);
 //           }
 //       }
 //   });
            }
            function showMonthSummary() {
                console.log('kicking');
                $.ajax({
                    url: '/index.php', type: 'POST', data: {get_data: 'month_summary'}, dataType: 'json',
                    success: function (jd) {
                        var data = new google.visualization.DataTable(jd);
                        //var table = new google.visualization.Table(document.getElementById('month_summary_table'));
                        //table.draw(data, {showRowNumber: true});
                        var chart = new google.visualization.BarChart(document.getElementById('month_summary_graph'));
                        chart.draw(data, {width: 600, height: 500});
                    },
                    error: function (e) {
                        console.log('Problem!');
                        console.log(e);
                        console.log(e.getAllResponseHeaders());
                    }
                });      
            }
            function showYearSummary() {
                $.ajax({
                        url: '/index.php',
                        type: 'POST',
                        data: {
                            get_data: 'year_summary'
                        },
                        dataType: 'json',
                        success: function (years) {
                            var htmllist = "";
                            for(y in years) {
                                var inverters = years[y];
                                htmllist += "<ul class='ytd'><li>" + y;
                                yeartotal = 0;
                                for(i in inverters) {
                                    var inverterproduction = eval(inverters[i]);
                                    htmllist += "<ul class='inverter'><li class='invertername'>" + i.substring(i.length - 3, i.length) + "</li><li>" + inverterproduction.toFixed(1) + " kWh</li></ul>";
                                    yeartotal += inverterproduction;
                                }
                                htmllist += "<ul class='total'><li>" + yeartotal.toFixed(1) + " kWh</li></ul>";
                                htmllist += "</li></ul>";
                            }
                            document.getElementById('ytd').innerHTML = htmllist;
                        },
                    error: function (e) {
                        console.log('Problem!');
                        console.log(e);
                    }
                });
            }
            
            function populatePage() {
                showDaySummary();
                showYearSummary();
                showMonthSummary();
                //drawChart();
            }
            
            function drawChart() {
                $.ajax({
                    url: '/index.php',
                    type: 'POST',
                    data: {
                        get_data: 'output_power'
                    },
                    dataType: 'json',
                    success: function (jd) {
                        console.log('origsuccess');
                        var data = new google.visualization.DataTable(jd);
                        var table = new google.visualization.Table(document.getElementById('table_div'));
                        table.draw(data, {showRowNumber: true});
                        ////var series = [];
                        ////series.push('Power');
                        ////var inverters = [];
                        ////inverters.push('174');
                        ////for(i=1; i<jd.cols.length; i++) {
                        ////if(jd.cols[i].label.lastIndexOf('Power', 0) === 0) {
                        ////    console.log("got one -> " + i);
                        ////  }
                        ////}
                        var chart = new google.visualization.LineChart(document.getElementById('chart_power'));
                        var seriesaxisarray = [];
                        for(i=0; i<jd.p.axisInfo.length; i++) {
                            seriesaxisarray[i] = { targetAxisIndex: jd.p.axisInfo[i] }
                        }
                        console.log(seriesaxisarray);
                        chart.draw(data, {width: 1200, height: 1000, interpolateNulls:true, hAxis: {format: 'yyyy-MM-dd HH:mm', slantedText: true}, legend: { position: 'bottom'}, series: seriesaxisarray});

                        google.visualization.events.addListener(chart, 'select', function () {
                            var sel = chart.getSelection();
                            if (typeof sel[0].row === 'undefined') {
                                var col = sel[0].column;
                                if (columns[col] == col) {
                                // hide the data series
                                    columns[col] = {
                                        label: data.getColumnLabel(col),
                                        type: data.getColumnType(col),
                                        calc: function () {
                                            return null;
                                        }
                        };
                
                // grey out the legend entry
                series[col - 1].color = '#CCCCCC';
            }
            else {
                // show the data series
                columns[col] = col;
                series[col - 1].color = null;
            }
            var view = new google.visualization.DataView(data);
            view.setColumns(columns);
            chart.draw(view, options);
        }
    });
///                        chart_wrapper.draw();
//thechart = chart_wrapper;


//                        new google.visualization.Dashboard(document.getElementById('dashboard')).
////                            bind(slider, chart_wrapper).
//                            //, category_control
//                            draw(data);
                    },
                    error: function (e) {
                        console.log('Problem!');
                        console.log(e);
                    }
                });
            }
            google.setOnLoadCallback(populatePage);
            google.load('visualization', '1', {'packages':['corechart', 'table', 'controls']});
            
            function toggleme() {
                console.log("toggleme running");
                thechart.setView({columns: [0,1]});
                thechart.draw();
                console.log("toggleme ran");
            }
            
        </script>
    </head>
  <body>
        <hr>
            <div id="dashboard">
                <div id="ytd"></div>
                <div id="dashboard_graphs">
                    <div id="day_summary_graph"></div>
                    <div id="month_summary_graph"></div>
                </div>
                <div id="day_summary_table"></div>
                <div id="month_summary_table"></div>
                <div id="time_control"></div>
                <div id="category_control"></div>
                <div id="chart_power"></div>
                <div id="table_div"></div>
            </div>
<!--        <hr>
        <form><input type=button value='Click' onclick='toggleme();'/></form> -->   
  </body>
</html>
