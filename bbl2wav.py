#!python3

import os
import sys

import pandas as pd
import numpy as np
from pydub import AudioSegment

from bbl_reading import read_and_decode_log, get_bbl_log_count


def parse(file_path):
    print("Parsing:", file_path)
    log_count = get_bbl_log_count(file_path)

    records = []
    df, header, name = read_and_decode_log(file_path, 1, '')
    bb_freq = header['blackbox_freq']
    debug_mode = header['debug_mode_name']
    craft_name = header['Craft name']
    batt_cells = header['bat_cells']
    batt_voltage = header['bat_ref_voltage']
    header['Armed times'] = log_count

    day_name = file_path.split('/')[5]
    # bbl_number = re.findall(r'\d+', file_path.split('/')[-1])[0]
    bbl_name = file_path.split('/')[-1].replace('.bbl', '')

    for i in range(0, log_count):
        if i > 0:  # we've already read it.
            df, header, name = read_and_decode_log(file_path, i + 1, '')
        len_sec = len(df) / bb_freq
        print(f'{i+1}/{log_count}: {len(df)} frames @ {bb_freq} Hz, debug_mode = {debug_mode}, length = {len_sec:.1f}')
        records.append((i + 1, df, len_sec))

    return records, bb_freq, debug_mode, craft_name, f'{batt_cells}S ({batt_voltage:.1f}V)'


def synthesize_sound(df_column, sampling_frequency, gain=1.0):
    max_val = df_column.max()
    min_val = df_column.min()
    # print(f'scaling between {min_val} and {max_val}')
    normalized_values = (df_column - min_val) / (max_val - min_val)
    normalized_values = 2 * normalized_values - 1  # Scale between -1 and 1
    normalized_values = np.clip(normalized_values * gain, -1, 1)

    signal = normalized_values
    duration = len(signal) / sampling_frequency
    data_ints = np.int32(signal * ((2**31)-1))

    audio = AudioSegment(
        data_ints.tobytes(),
        frame_rate=sampling_frequency,
        sample_width=data_ints.itemsize,
        channels=1
    )
    return audio, duration


def process_bbl(file_path):
    records, bb_freq, debug_mode, craft_name, battery = parse(file_path)

    for idx, df, len_sec in records:
        if len(df) < 100:
            print(f'Skipped.')
            continue

        gyro_rate_limit = 5000

        for axis in ['roll', 'pitch', 'yaw']:
            axis_channel = f'gyro_scaled_{axis}'
            output_file = file_path.replace('.bbl', '') + f'_{idx}_{axis}.wav'

            if axis_channel not in df.columns:
                print(f'{axis_channel} not found in the log.')
                exit(1)

            audio, duration = synthesize_sound(
                df[axis_channel].clip(
                    lower=-gyro_rate_limit,
                    upper=gyro_rate_limit
                ),
                bb_freq,
                gain=1
            )

            audio.export(output_file, format="wav")
            print(f'Generated {output_file}')


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f'Usage: {sys.argv[0]} <path to .bbl file>')
        if len(sys.argv) > 2:
            print(f'Too many arguments: {sys.argv[1:]}')
        exit(1)

    file = sys.argv[1]

    if not os.path.isfile(file):
        print(f'"{file}" is not a file.')
        exit(1)

    process_bbl(file)
