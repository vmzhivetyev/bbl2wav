import math
import os

import pandas as pd
import numpy as np


def is_float(element: any) -> bool:
    if element is None:
        return False
    try:
        float(element)
        return True
    except ValueError:
        return False


class LogParser:
    """
    This is based on https://github.com/betaflight/blackbox-log-viewer
    """
    def __init__(self, blackbox_header: dict):
        self.params = blackbox_header

        import struct

        """
         'gyro_scale' value in .bbl is stored as hex string, e.g. '0x3f800000'.
         Parser reads it as int but it's actually a float.
         So we just keep the int bytes and reinterpret it as float bytes.
        """
        self.params['gyro_scale'] = struct.unpack('f', struct.pack('I', self.params['gyro_scale']))[0]

        """
        /* Baseflight uses a gyroScale that'll give radians per microsecond as output, whereas Cleanflight produces degrees
         * per second and leaves the conversion to radians per us to the IMU. Let's just convert Cleanflight's scale to
         * match Baseflight so we can use Baseflight's IMU for both: */
        """
        firmware_type = self.params['Firmware type'].lower()
        if 'inav' in firmware_type or 'flight' in firmware_type:
            self.params['gyro_scale'] = self.params['gyro_scale'] * (math.pi / 180.0) * 0.000001

        self.FAST_PROTOCOL = [
            "PWM",
            "ONESHOT125",
            "ONESHOT42",
            "MULTISHOT",
            "BRUSHED",
            "DSHOT150",
            "DSHOT300",
            "DSHOT600",
            "DSHOT1200",  # deprecated
            "PROSHOT1000",
        ]

    def parse_dshot_rpm_telemetry(self, value, motor_poles=0) -> float:
        """
        :param value: as is in log file
        :param motor_poles: number of poles in the motor. If 0 then use value from `self.params['motor_poles']`.
        :return: motor rpm
        """
        motor_poles = motor_poles or self.params['motor_poles']
        return value * 200 / motor_poles  # + " rpm / " + (value * 3.333 / motor_poles).toFixed(0) + ' hz';

    def accRawToGs(self, value):
        return value / self.params['acc_1G']

    def gyroRawToDegreesPerSecond(self, value):
        highResolutionScale = 10 if self.params['blackbox_high_resolution'] > 0 else 1
        return self.params['gyro_scale'] * 1000000 / (math.pi / 180.0) * value / highResolutionScale

    def rcMotorRawToPctPhysical(self, value):
        MAX_MOTOR_NUMBER = 8
        DSHOT_MIN_VALUE = 48
        DSHOT_MAX_VALUE = 2047
        DSHOT_RANGE = DSHOT_MAX_VALUE - DSHOT_MIN_VALUE
        ANALOG_MIN_VALUE = 1000
        if (self.isDigitalProtocol()):
            motorPct = ((value - DSHOT_MIN_VALUE) / DSHOT_RANGE) * 100
        else:
            MAX_ANALOG_VALUE = self.params['maxthrottle']
            MIN_ANALOG_VALUE = self.params['minthrottle']
            ANALOG_RANGE = MAX_ANALOG_VALUE - MIN_ANALOG_VALUE
            motorPct = ((value - MIN_ANALOG_VALUE) / ANALOG_RANGE) * 100
        return min(max(motorPct, 0.0), 100.0)

    def isDigitalProtocol(self):
        proto = self.FAST_PROTOCOL[self.params['motor_pwm_protocol']]
        if proto == 'BRUSHED':
            return False
        return True


def get_bbl_log_count(file_path):
    from orangebox import Parser
    parser = Parser.load(file_path)
    log_count = parser.reader.log_count
    return log_count


def read_bbl(file_path, log_index):
    from orangebox import Parser
    parser = Parser.load(file_path, log_index)
    headers = parser.headers
    log_count = parser.reader.log_count

    # Print headers
    # print("headers:", parser.headers)
    # print("field names:", parser.field_names)
    # print("log count:", parser.reader.log_count)

    rows = []
    for frame in parser.frames():
        # print("frame:", frame.data)
        rows.append(frame.data)

    # print("events:", parser.events)

    df = pd.DataFrame(rows, columns=parser.field_names)
    return df, headers, log_count


def read_and_decode_log(file_path, flight_num, description, trim=None):
    print('Reading bbl...')

    df, header, log_count = read_bbl(file_path, flight_num)

    print('Decoding data...')

    parser = LogParser(blackbox_header=header)

    # Parse values

    # header

    pid_freq = int(1000000 / header['looptime'] / header['pid_process_denom'])
    assert pid_freq in [4000, 8000]

    blackbox_denom = header['P interval']
    blackbox_freq = pid_freq / blackbox_denom
    assert blackbox_freq in [250, 500, 1000, 2000, 4000, 8000]
    assert blackbox_freq <= pid_freq

    expected_delta_time = 1 / blackbox_freq
    # if len(df):
    #     avg_delta_time = df['log_time'].diff().min()
    #     assert abs(expected_delta_time - avg_delta_time) < 0.001

    header['pid_freq'] = pid_freq
    header['blackbox_freq'] = blackbox_freq
    header['delta_time'] = expected_delta_time

    header['bat_cells'], header['bat_ref_voltage'] = estimate_batt_cells(header)

    # MOTORS

    header['debug_mode_name'] = {
        6: 'GYRO_SCALED',
        45: 'DSHOT_RPM_TELE',
        80: 'THRUST_IMBALANCE?',
        46: 'RPM_FILTER',
        12: 'ESC_SENSOR_RPM',
    }[header['debug_mode']]

    if header['debug_mode_name'] == 'GYRO_SCALED':
        df['gyro_scaled_roll'] = df['debug[0]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))
        df['gyro_scaled_pitch'] = df['debug[1]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))
        df['gyro_scaled_yaw'] = df['debug[2]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))

    if header['debug_mode_name'] == 'DSHOT_RPM_TELE':
        df['m1_rpm'] = df['debug[0]'].apply(parser.parse_dshot_rpm_telemetry)
        df['m2_rpm_wrong'] = df['debug[1]'].apply(parser.parse_dshot_rpm_telemetry)
        df['m2_rpm'] = df['debug[1]'].apply(lambda x: parser.parse_dshot_rpm_telemetry(x, 14))
        df['m3_rpm'] = df['debug[2]'].apply(parser.parse_dshot_rpm_telemetry)
        df['m4_rpm'] = df['debug[3]'].apply(parser.parse_dshot_rpm_telemetry)


    # right rear

    df['m1_pct'] = df['motor[0]'].apply(parser.rcMotorRawToPctPhysical)
    df['m2_pct'] = df['motor[1]'].apply(parser.rcMotorRawToPctPhysical)
    df['m3_pct'] = df['motor[2]'].apply(parser.rcMotorRawToPctPhysical)
    df['m4_pct'] = df['motor[3]'].apply(parser.rcMotorRawToPctPhysical)

    # GYRO

    df['gyro_roll'] = df['gyroADC[0]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))
    df['gyro_pitch'] = df['gyroADC[1]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))
    df['gyro_yaw'] = df['gyroADC[2]'].apply(lambda x: parser.gyroRawToDegreesPerSecond(x))

    # Accelerometer

    df['acc_x'] = df['accSmooth[0]'] / header['acc_1G']
    df['acc_y'] = df['accSmooth[1]'] / header['acc_1G']
    df['acc_z'] = df['accSmooth[2]'] / header['acc_1G']
    df['acc'] = (df['acc_x']**2 + df['acc_y']**2 + df['acc_z']**2)**(1/2)

    # PID

    df['pid_i_roll'] = df['axisI[0]']
    df['pid_i_pitch'] = df['axisI[1]']
    df['pid_i_yaw'] = df['axisI[2]']

    df['pid_d_roll'] = df['axisD[0]']
    df['pid_d_pitch'] = df['axisD[1]']

    # Baro

    df['altitude_m'] = df['baroAlt'] / 100

    df['vertical_speed'] = df['altitude_m'].diff() / header['delta_time']
    df['pid_p_roll'] = df['axisP[0]']
    df['pid_p_pitch'] = df['axisP[1]']

    if len(df):
        df['log_time'] = (df['time'] - df['time'][0])/1e6

    if trim:
        old_len = len(df)
        trim = (trim[0] or 0, trim[1] or df['log_time'].dropna().iloc[-1])
        print(f"Trimming {description} in range: {trim}")
        df = df[(df["log_time"] > trim[0]) & (df["log_time"] < trim[1])]
        assert old_len > len(df)

    file_name = os.path.basename(file_path)

    print('Parsing done')

    return df, header, f'{blackbox_freq:.0f}Hz {file_name} ({flight_num}/{log_count}) {description}'


def estimate_batt_cells(header):
    ADCVREF = 33

    # ADC is 12 bit (i.e. max 0xFFF), voltage reference is 3.3V, vbatscale is premultiplied by 100
    vbat_millivolts = (header['vbatref'] * ADCVREF * 10 * header['vbat_scale']) / 0xFFF
    vbat_max_cell_voltage = header['vbatcellvoltage'][2]

    for i in np.arange(2, 10, 2, int):
        if vbat_millivolts < i * vbat_max_cell_voltage * 10:
            return int(i), vbat_millivolts / 1e3
    raise Exception()
