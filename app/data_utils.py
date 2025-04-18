#!/usr/bin/python3
"""
Volcano InSAR Interpretation Workbench

SPDX-License-Identifier: MIT

Copyright (C) 2021-2023 Government of Canada

Authors:
  - Chloe Lam <chloe.lam@nrcan-rncan.gc.ca>
"""
import datetime
from datetime import datetime as dt
import json
import os
import sys
import logging
from io import StringIO

import numpy as np
import pandas as pd
import requests
import dash
from dash import html
from dash_leaflet import Marker, Tooltip
from dotenv import load_dotenv
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from pages.components.observation_log_components import (
    logs_list_ui,
    observation_log_ui
)

from global_variables import (
    BASELINE_DTICK,
    BASELINE_MAX,
    CMAP_NAME,
    COH_LIMS,
    DAYS_PER_YEAR,
    MAX_YEARS,
    YEAR_AXES_COUNT
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.get_latest_baselines import get_latest_baselines
from scripts.get_latest_coh_matrices import get_latest_coh_matrices
from scripts.get_latest_insar_pairs import get_latest_insar_pairs

logger = logging.getLogger(__name__)


def get_latest_csv():
    """fetch latest csv files"""
    get_latest_baselines()
    get_latest_coh_matrices()
    get_latest_insar_pairs()


def get_config_params():
    """
    Retrieve configuration parameters from environment variables.

    This function loads variables from a .env file into the environment
    and retrieves specific environment variables related to AWS, API,
    and other configurations. It creates a dictionary storing these
    configuration parameters and returns it.

    Returns:
        dict: A dictionary containing configuration parameters. Keys
        correspond to environment variable names, and values are the
        corresponding values retrieved from the environment.
    """
    # Load variables from .env file into environment
    load_dotenv()
    # List of environment variable names
    env_variables = [
        'AWS_BUCKET_NAME',
        'AWS_RAW_BUCKET',
        'AWS_TILES_URL',
        'API_VRRC_IP',
        'WORKBENCH_HOST',
        'WORKBENCH_PORT'
    ]
    # Dictionary to store configuration parameters
    config_params = {}
    # Retrieve configuration parameters using os.getenv()
    # and store them in the dictionary
    for var_name in env_variables:
        config_params[var_name] = os.getenv(var_name)
    # Return the dictionary of configuration parameters
    return config_params


def parse_dates(input_string):
    """
    Parses a string containing two dates in the format
    'yyyymmdd_HH_yyyymmdd' and returns them formatted
    as 'yyyy/mm/dd - yyyy/mm/dd'.

    Args:
        input_string (str): A string containing two dates in 'yyyymmdd' format,
        separated by some characters, e.g., '20220821_HH_20220914'.

    Returns:
        str: A formatted string representing the two dates in the format
        'yyyy/mm/dd - yyyy/mm/dd'.

    Raises:
        ValueError: If the input string does not contain valid date
        segments or is in an unexpected format.
    """
    try:
        # Check input has at least 19 characters
        if len(input_string) < 19:
            raise ValueError(
                "Input string is too short to contain two valid dates."
            )

        # Extract the start and end dates
        start_date = input_string[0:8]
        end_date = input_string[12:20]

        # Check the extracted dates are digits and have the expected length
        if not (start_date.isdigit() and len(start_date) == 8):
            raise ValueError(f"Invalid start date format: {start_date}")
        if not (end_date.isdigit() and len(end_date) == 8):
            raise ValueError(f"Invalid end date format: {end_date}")

        # Format the dates into yyyy/mm/dd
        formatted_start_date = (
            f'{start_date[:4]}/'
            f'{start_date[4:6]}/'
            f'{start_date[6:]}'
        )
        formatted_end_date = (
            f'{end_date[:4]}/'
            f'{end_date[4:6]}/'
            f'{end_date[6:]}'
        )

        # Return the final formatted string
        return f"{formatted_start_date} - {formatted_end_date}"

    except Exception as e:
        raise ValueError(f"Error parsing input string: {e}") from e


def get_latest_quakes_chis_fsdn():
    """Query the CHIS fsdn for latest earthquakes"""
    url = 'https://earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query'
    # Parameters for the query
    params = {
        'format': 'text',
        'starttime': (
            datetime.datetime.today() - datetime.timedelta(days=365)
        ).strftime('%Y-%m-%d'),
        'endtime': datetime.datetime.today().strftime('%Y-%m-%d'),
        'eventtype': 'earthquake',
    }
    # Make the request
    try:
        response = requests.get(url,
                                params=params,
                                timeout=10, verify=False)
        if response.status_code == 200:
            # Parse the response text to a dataframe
            df = pd.read_csv(
                StringIO(response.text), delimiter='|'
            )
            # Create marker colour code based on event age
            df['Time_Delta'] = pd.to_datetime(
                df['Time']) - datetime.datetime.now(datetime.timezone.utc)
            df['Time_Delta'] = pd.to_numeric(
                -df['Time_Delta'].dt.days,
                downcast='integer'
            )
            conditions = [
                (df['Time_Delta'] <= 2),
                (df['Time_Delta'] > 2) & (df['Time_Delta'] <= 7),
                (df['Time_Delta'] > 7) & (df['Time_Delta'] <= 31),
                (df['Time_Delta'] > 31)
            ]
            values = ['red', 'orange', 'yellow', 'white']
            df['quake_colour'] = np.select(conditions, values)
            df.sort_values(by='#EventID')
    except requests.exceptions.ConnectionError:
        df = pd.DataFrame()
        df['#EventID'] = None
    return df


def get_latest_quakes_chis_fsdn_site(initial_target, target_centres):
    """Query the CHIS fsdn for latest earthquakes"""
    url = 'https://earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query'

    # Initial lat long for initial target
    center_lat_long = target_centres[initial_target]
    center_latitude = center_lat_long[0]
    center_longitude = center_lat_long[1]

    # Parameters for the query
    params = {
        'format': 'text',
        'starttime': (
            datetime.datetime.today() - datetime.timedelta(days=365)
        ).strftime('%Y-%m-%d'),
        'endtime': datetime.datetime.today().strftime('%Y-%m-%d'),
        'eventtype': 'earthquake',
        # Geographic boundaries
        'minlatitude': center_latitude - 1,
        'maxlatitude': center_latitude + 1,
        'minlongitude': center_longitude - 2,
        'maxlongitude': center_longitude + 2,
    }
    # Initialize df to an empty df to ensure it is always defined
    df = pd.DataFrame()
    # Make the request
    try:
        response = requests.get(url,
                                params=params,
                                timeout=10, verify=False)
        if response.status_code == 200:
            # Parse the response text to a dataframe
            df = pd.read_csv(
                StringIO(response.text), delimiter='|'
            )
            c1 = df['Latitude'] >= center_latitude - 1
            c2 = df['Latitude'] <= center_latitude + 1
            c3 = df['Longitude'] >= center_longitude - 2
            c4 = df['Longitude'] <= center_longitude + 2
            # Parse the boundary lat long
            df = df[c1 & c2 & c3 & c4]
            # Create marker colour code based on event age
            df['Time_Delta'] = pd.to_datetime(
                df['Time']
            ) - datetime.datetime.now(datetime.timezone.utc)
            df['Time_Delta'] = pd.to_numeric(
                -df['Time_Delta'].dt.days, downcast='integer'
            )
            conditions = [
                (df['Time_Delta'] <= 2),
                (df['Time_Delta'] > 2) & (df['Time_Delta'] <= 7),
                (df['Time_Delta'] > 7) & (df['Time_Delta'] <= 31),
                (df['Time_Delta'] > 31)
            ]
            values = ['red', 'orange', 'yellow', 'white']
            df['quake_colour'] = np.select(conditions, values)
            if '#EventID' in df.columns:
                df.sort_values(by='#EventID')
    except requests.exceptions.ConnectionError:
        df = pd.DataFrame()
        df['#EventID'] = None
    return df


def read_targets_geojson():
    """Query VRRC API for All Targets FootPrints"""
    try:
        vrrc_api_ip = config['API_VRRC_IP']
        response = requests.get(f'http://{vrrc_api_ip}/targets/geojson/',
                                timeout=10, verify=False)
        response_geojson = json.loads(response.content)
        unrest_table_df = pd.read_csv('app/Data/unrest_table.csv')
        calculate_and_append_centroids(response_geojson)
        for feature in response_geojson['features']:
            if unrest_table_df.loc[
                unrest_table_df['Site'] == feature['properties']['name_en']
            ]['Unrest'].values.size > 0:
                unrest_bool = unrest_table_df.loc[
                    unrest_table_df['Site'] == feature['properties']['name_en']
                ]['Unrest'].values[0]
            else:
                unrest_bool = False
            feature['properties']['tooltip'] = html.Div([
                html.Span(f"Site: {feature['id']}"), html.Br(),
                html.Span("Last Checked by: None"), html.Br(),
                html.Span("Most Recent SLC: None"), html.Br(),
                html.Span("Unrest Observed: "),
                html.Span(f"{unrest_bool}",
                          style={
                              'color': 'red' if unrest_bool else 'green'})])
            # feature['properties']['icon'] = 'assets/greenVolcano.png'
    except requests.exceptions.ConnectionError:
        response_geojson = None
        # pass
    return response_geojson


def get_green_volcanoes():
    """Return a list of green volcano points"""
    logger.info("GET green volc")
    targets_geojson = read_targets_geojson()
    summary_table_df = build_summary_table(targets_geojson)
    try:
        green_point_features = []
        green_icon = {
            "iconUrl": dash.get_asset_url('green_volcano_transparent.png'),
            "iconSize": [25, 25]
        }
        for feature in targets_geojson['features']:
            if feature['id'].startswith('A'):
                cond1 = feature['geometry']['type'] == 'Point'
                cond2 = summary_table_df.loc[
                    summary_table_df[
                        'Site'
                    ] == feature['properties']['name_en']
                ]['Unrest'].values[0]
                if (cond1 and not cond2):
                    green_point_features.append(feature)
        green_markers = [
            Marker(position=[point['geometry']['coordinates'][1],
                             point['geometry']['coordinates'][0]],
                   icon=green_icon,
                   children=Tooltip(html.P(point['properties']['tooltip'])),
                   id=f"marker_{point['properties']['name_en']}"
                   )
            for point in green_point_features
        ]
    except TypeError:
        green_markers = [Marker(position=[0., 0.],
                                icon=green_icon,
                                children=Tooltip("API Error"),
                                id="TypeError_green")]
    return green_markers


def get_red_volcanoes():
    """Return a list of red volcano points"""
    logger.info("GET red volc")
    targets_geojson = read_targets_geojson()
    summary_table_df = build_summary_table(targets_geojson)
    try:
        red_point_features = []
        red_icon = {
            "iconUrl": dash.get_asset_url('red_volcano_transparent.png'),
            "iconSize": [25, 25]
        }
        for feature in targets_geojson['features']:
            if feature['id'].startswith('A') or feature['id'] == 'Edgecumbe':
                cond1 = feature['geometry']['type'] == 'Point'
                cond2 = summary_table_df.loc[
                    summary_table_df[
                        'Site'
                    ] == feature['properties']['name_en']
                ]['Unrest'].values[0]
                if (cond1 and cond2):
                    red_point_features.append(feature)
        red_markers = [
            Marker(position=[point['geometry']['coordinates'][1],
                             point['geometry']['coordinates'][0]],
                   icon=red_icon,
                   children=Tooltip(html.P(point['properties']['tooltip'])),
                   id=f"marker_{point['properties']['name_en']}"
                   )
            for point in red_point_features
        ]
    except TypeError:
        red_markers = [Marker(position=[0., 0.],
                              icon=red_icon,
                              children=Tooltip("API Error"),
                              id="TypeError_red")]
    return red_markers


def get_api_response(vrrc_api_ip, route):
    """Get a response from the vrrc API given an ip and a route"""
    try:
        response = requests.get(f'http://{vrrc_api_ip}/{route}/',
                                timeout=10, verify=False)
        response.raise_for_status()
        response_dict = json.loads(response.text)
        return response_dict
    except requests.exceptions.RequestException as exception:
        response_dict = {}
        response_dict['API Response Error'] = [exception.args[0]]
        return response_dict


def calculate_centroid(coords):
    """Calculate a centroid given a list of x,y coordinates"""
    num_points = len(coords)
    total_x = 0
    total_y = 0
    for x, y in coords:
        total_x += x
        total_y += y
    centroid_x = total_x / num_points
    centroid_y = total_y / num_points
    return [centroid_x, centroid_y]


def calculate_and_append_centroids(geojson_dict):
    """append polygon centroid to geojson object"""
    for feature in geojson_dict['features']:
        geometry = feature['geometry']
        centroid = calculate_centroid(geometry['coordinates'][0])
        feature['geometry']['type'] = 'Point'
        feature['geometry']['coordinates'] = centroid


def calc_polygon_centroid(coordinates):
    """Calculate centroid from geojson coordinates"""
    # Extract the coordinates
    x_coords = [point[0] for point in coordinates]
    y_coords = [point[1] for point in coordinates]
    # Calculate the centroid
    centroid_x = sum(x_coords) / len(coordinates)
    centroid_y = sum(y_coords) / len(coordinates)
    return round(centroid_x, 2), round(centroid_y, 2)


def populate_beam_selector(vrrc_api_ip):
    """create dict of site_beams and centroid coordinates"""
    beam_response_dict = get_api_response(vrrc_api_ip, 'beams')
    targets_response_dict = get_api_response(vrrc_api_ip, 'targets')
    beam_dict = {}
    for beam in beam_response_dict:
        try:
            beam_string = beam['short_name']
            for target in targets_response_dict:
                if target['label'] == beam['target_label']:
                    matching_target = target
            site_string = matching_target['name_en']
            site_beam_string = f'{site_string}_{beam_string}'
            target_coordinates = matching_target['geometry']['coordinates'][0]
            centroid_x, centroid_y = calc_polygon_centroid(target_coordinates)
            beam_dict[site_beam_string] = [centroid_y, centroid_x]
        except TypeError:
            beam_dict['API Response Error'] = [50.64, -123.60]
    return beam_dict


def pivot_and_clean(coh_long):
    """Convert long-form coherence to wide-form and clean it up."""
    coh_wide = coh_long.pivot(
        index='delta_days',
        columns='second_date',
        values='coherence')
    # include zero baseline even though it will never be valid
    coh_wide.loc[0, :] = np.NaN
    coh_wide.sort_index(inplace=True)
    # because hovertemplate 'f' format doesn't handle NaN properly
    coh_wide = coh_wide.round(2)

    cw_last_col = coh_wide.max(axis='columns').last_valid_index()
    cw_first_ind = coh_wide.max(axis='index').first_valid_index()
    cw_last_ind = coh_wide.max(axis='index').last_valid_index()
    cw_col = coh_wide.columns
    # trim empty edges
    coh_wide = coh_wide.loc[
        (coh_wide.index >= 0) & (coh_wide.index <= cw_last_col),
        (cw_col >= cw_first_ind) & (cw_col <= cw_last_ind)
    ]
    return coh_wide


def pivot_and_clean_insar(insar_long):
    """Convert long-form coherence to wide-form and clean it up."""
    insar_wide = insar_long.pivot(
        index='delta_days',
        columns='second_date',
        values='insar_pair')
    # include zero baseline even though it will never be valid
    insar_wide.loc[0, :] = np.NaN
    insar_wide.sort_index(inplace=True)
    # because hovertemplate 'f' format doesn't handle NaN properly
    insar_wide = insar_wide.round(2)
    # trim empty edges
    first_valid_row_index = insar_wide.dropna(how='all').index[0]
    last_valid_row_index = insar_wide.dropna(how='all').index[-1]
    first_valid_col_index = insar_wide.dropna(axis=1, how='all').columns[0]
    last_valid_col_index = insar_wide.dropna(axis=1, how='all').columns[-1]
    insar_wide = insar_wide.loc[first_valid_row_index:last_valid_row_index,
                                first_valid_col_index:last_valid_col_index]
    return insar_wide


def pivot_and_clean_dates(coh_long, coh_wide):
    """Convert long-form df to wide-form date matrix matching coh_wide."""
    coh_long = coh_long.drop(
        coh_long[coh_long.second_date < coh_long.first_date].index
    )
    date_wide = coh_long.pivot(
        index='delta_days',
        columns='second_date',
        values='first_date')
    date_wide = date_wide.map(lambda x: pd.to_datetime(x)
                              .strftime('%b %d, %Y') if x is not pd.NaT
                              else x)
    # remove some columns so that date_wide has
    # the same columns as coh_wide
    common_cols = list(set(date_wide.columns).intersection(coh_wide.columns))
    common_cols.sort()
    date_wide = date_wide[common_cols]
    # date_wide.drop(columns=date_wide.columns[0], axis=1,  inplace=True)
    return date_wide


def plot_coherence(coh_long, insar_long):
    """Plot coherence for different baselines as a function of time."""
    print('PLOT COHERENCE', coh_long, insar_long)
    fig = make_subplots(
        rows=YEAR_AXES_COUNT, cols=1, shared_xaxes=True,
        start_cell='bottom-left', vertical_spacing=0.02,
        y_title='Temporal baseline [days]')
    if coh_long is None:
        return fig

    coh_long['delta_days'] = (
        coh_long.second_date - coh_long.first_date
    ).dt.days
    coh_wide = pivot_and_clean(coh_long)
    date_wide = pivot_and_clean_dates(coh_long, coh_wide)

    if insar_long is not None:
        insar_long['delta_days'] = (
            insar_long.second_date - insar_long.first_date
        ).dt.days
        insar_wide = pivot_and_clean_insar(insar_long)
        insar_date_wide = pivot_and_clean_dates(insar_long, insar_wide)
        insar_colorscale = [
            [0, 'rgba(0,0,0,0)'],
            [1, 'grey']
        ]

    for year in range(YEAR_AXES_COUNT):
        if insar_long is not None:
            # Grey heatmap for potential insar pair
            fig.add_trace(
                go.Heatmap(
                    z=insar_wide.values,
                    x=insar_wide.columns,
                    y=insar_wide.index,
                    xgap=1,
                    ygap=1,
                    customdata=insar_date_wide,
                    hovertemplate=(
                        'Start Date: %{customdata}<br>'
                        'End Date: %{x}<br>'
                        'Temporal Baseline: %{y} days<br>'
                        'Value: %{z}'),
                    colorscale=insar_colorscale,
                    showscale=False,
                    opacity=0.5),
                row=year + 1, col=1)
        # Colored heatmap for processed insar pairs
        fig.add_trace(
            go.Heatmap(
                z=coh_wide.values,
                x=coh_wide.columns,
                y=coh_wide.index,
                xgap=1,
                ygap=1,
                customdata=date_wide,
                hovertemplate=(
                    'Start Date: %{customdata}<br>'
                    'End Date: %{x}<br>'
                    'Temporal Baseline: %{y} days<br>'
                    'Coherence: %{z}'),
                coloraxis='coloraxis'),
            row=year + 1, col=1)
        if year == 0:
            baseline_limits = [0, BASELINE_MAX]
        else:
            baseline_limits = list(
                int(
                    year * DAYS_PER_YEAR
                ) + BASELINE_MAX / 2 * np.array([-1, 1])
            )
        second_date_limits = [
            max(
                coh_wide.columns.min(),
                coh_wide.columns.max() - pd.to_timedelta(
                    DAYS_PER_YEAR * MAX_YEARS, 'days'
                )
            ) - pd.to_timedelta(4, 'days'),
            coh_wide.columns.max() + pd.to_timedelta(4, 'days')
        ]
        fig.update_yaxes(
            range=baseline_limits,
            dtick=BASELINE_DTICK,
            scaleanchor='x',
            row=year + 1, col=1)
        fig.update_xaxes(
            range=second_date_limits,
            row=year + 1, col=1)

    fig.update_layout(
        margin={'l': 65, 'r': 0, 't': 5, 'b': 5},
        coloraxis={
            'colorscale': CMAP_NAME,
            'cmin': COH_LIMS[0],
            'cmax': COH_LIMS[1],
            'colorbar': {
                'title': 'Coherence',
                'dtick': 0.1,
                'ticks': 'outside',
                'tickcolor': 'white',
                'thickness': 20,
            }},
        showlegend=False)

    return fig


def plot_baseline(df_baseline, df_cohfull):
    """Plot perpendicular baseline as a function of time."""
    if df_baseline is None or df_cohfull is None:
        bperp_combined_fig = go.Figure()
        return bperp_combined_fig
    # if :
    #     bperp_combined_fig = go.Figure()
    #     return bperp_combined_fig
    bperp_scatter_fig = go.Scatter(x=df_baseline['second_date'],
                                   y=df_baseline['bperp'],
                                   mode='markers')
    df_baseline_edge = df_cohfull[df_cohfull['coherence'].notna()]
    df_baseline_edge = df_baseline_edge.drop(columns=['coherence'])
    df_baseline_edge = pd.merge(df_baseline_edge,
                                df_baseline[['second_date', 'bperp']],
                                right_on='second_date',
                                left_on='first_date',
                                how='left')
    df_baseline_edge = df_baseline_edge.drop(columns=['second_date_y'])
    df_baseline_edge = \
        df_baseline_edge.rename(columns={"second_date_x": "second_date",
                                         "bperp": "bperp_reference_date"})
    df_baseline_edge = pd.merge(df_baseline_edge,
                                df_baseline[['second_date', 'bperp']],
                                right_on='second_date',
                                left_on='second_date',
                                how='left')

    df_baseline_edge = df_baseline_edge.rename(
        columns={"bperp": "bperp_pair_date"})
    df_baseline_edge = df_baseline_edge[
        df_baseline_edge['bperp_reference_date'].notna()]

    edge_x = []
    edge_y = []

    for _, edge in df_baseline_edge.iterrows():
        edge_x.append(edge['first_date'])
        edge_x.append(edge['second_date'])
        edge_y.append(edge['bperp_reference_date'])
        edge_y.append(edge['bperp_pair_date'])

    bperp_line_fig = go.Scatter(x=edge_x, y=edge_y,
                                line={"width": 0.5, "color": '#888'},
                                mode='lines')

    bperp_combined_fig = go.Figure(data=[bperp_line_fig, bperp_scatter_fig])
    bperp_combined_fig.update_layout(yaxis_title="Perpendicular Baseline (m)",
                                     margin={'l': 65, 'r': 0, 't': 5, 'b': 5})
    bperp_combined_fig.update(layout_showlegend=False)

    return bperp_combined_fig


def plot_annotation_tab():
    """plot annotation tab"""
    def get_end_date(log):
        return dt.strptime(log['endDateObserved'], '%Y-%m-%d')
    # example data
    user1 = {
        'name': 'User 1',
        'email': 'user1@gmail.com'
    }

    user2 = {
        'name': 'User 2',
        'email': 'user2@gmail.com'
    }

    user3 = {
        'name': 'User 3',
        'email': 'user3@gmail.com'
    }

    log1 = {
        'id': 0,
        'user': user1,
        'dateAddedModified': '2024-09-10',
        'endDateObserved': '2024-09-10',
        'dateRange': 48,
        'coherencePresent': 'Yes',
        'confidence': 80,
        'furtherInterpretationNeeded': True,
        'interpretationLatitude': 111.11,
        'interpretationLongitude': 123.00,
        'insarPhaseAnomalies': [
            'Magmatic Deformation',
            'Slope Movement',
            'Glacial Movement'
        ],
        'insarPhaseAnomaliesOther': '',
        'additionalComments': 'hhhhhiii'
    }

    log2 = {
        'id': 1,
        'user': user2,
        'dateAddedModified': '2024-09-10',
        'endDateObserved': '2024-09-12',
        'dateRange': 28,
        'coherencePresent': 'Yes',
        'confidence': 20,
        'furtherInterpretationNeeded': True,
        'interpretationLatitude': 111.11,
        'interpretationLongitude': 123.00,
        'insarPhaseAnomalies': [
            'Magmatic Deformation',
            'Slope Movement',
            'Other',
            'Atmospheric Phase Error'
        ],
        'insarPhaseAnomaliesOther': 'other reasoning',
        'additionalComments': 'this is greatttt'
    }

    log3 = {
        'id': 2,
        'user': user3,
        'dateAddedModified': '2024-09-10',
        'endDateObserved': '2024-09-07',
        'dateRange': 48,
        'coherencePresent': 'Yes',
        'confidence': 80,
        'furtherInterpretationNeeded': True,
        'interpretationLatitude': 111.11,
        'interpretationLongitude': 123.00,
        'insarPhaseAnomalies': [
            'Magmatic Deformation',
            'Slope Movement',
            'Glacial Movement'
        ],
        'insarPhaseAnomaliesOther': '',
        'additionalComments': 'hhhhhiii'
    }

    log4 = {
        'id': 3,
        'user': user3,
        'dateAddedModified': '2024-09-10',
        'endDateObserved': '2024-09-18',
        'dateRange': 48,
        'coherencePresent': 'Yes',
        'confidence': 90,
        'furtherInterpretationNeeded': True,
        'interpretationLatitude': 111.11,
        'interpretationLongitude': 123.00,
        'insarPhaseAnomalies': [
            'Magmatic Deformation',
            'Slope Movement',
            'Glacial Movement'
        ],
        'insarPhaseAnomaliesOther': '',
        'additionalComments': 'hhhhhiii'
    }

    users = [user1, user2, user3]
    logs = [
        log1,
        log2,
        log3,
        log4
    ]
    cleaned_logs = [log[0] if isinstance(log, tuple) else log for log in logs]
    # most recent log first
    sorted_logs = sorted(cleaned_logs, key=get_end_date, reverse=True)
    observation_log_ui_width = 70
    return html.Div(
        style={
            'display': 'flex',
            'flexDirection': 'row',
            'alignItems': 'stretch',
            'backgroundColor': 'white',
            'margin': '0 1px 5px',
            'height': '33vh',
            'border': '1px solid black'
        },
        children=[
            html.Div(
                id='observation_log_container',
                children=observation_log_ui(users, log=None),
                style={'width': f'{observation_log_ui_width}%'}
            ),
            logs_list_ui(sorted_logs, 100 - observation_log_ui_width),
        ],
    )


def build_summary_table(targs_geojson):
    """Build a summary table with volcanoes and info on their unrest"""
    def date_difference(date_string):
        date = dt.strptime(date_string, "%Y-%m-%d").date()
        return (dt.today().date() - date).days

    logger.info('BUILD summary table')
    try:
        targets_df = pd.json_normalize(targs_geojson,
                                       record_path=['features'])
        targets_df = targets_df[targets_df['id'].str.contains('^A|Edgecumbe')]
        targets_df['latest SAR Image Date'] = None
        targets_df = targets_df.rename(columns={'properties.name_en': 'Site'})
        unrest_table_df = pd.read_csv('app/Data/unrest_table.csv')
        # targets_df['Unrest'] = None
        targets_df = pd.merge(targets_df,
                              unrest_table_df,
                              on='Site',
                              how='left')
        for site in targets_df['id']:
            site_index = targets_df.loc[targets_df['id'] == site].index[0]
            try:
                url = config['API_VRRC_IP']
                response = requests.get(
                    f"http://{url}/targets/{site}",
                    timeout=10, verify=False)
                response_geojson = json.loads(response.content)
                if isinstance(response_geojson['last_slc_datetime'], str):
                    last_slc_date = response_geojson['last_slc_datetime'][0:10]
                    last_slc_beam_mode = response_geojson['last_slc_beam_mode']
                    format_output = (
                        f'{last_slc_beam_mode} - '
                        f'{last_slc_date} ('
                        f'{date_difference(last_slc_date)} days ago)'
                    )
                    targets_df.loc[site_index,
                                   'Latest SAR Image'
                                   ] = format_output
            except requests.exceptions.ConnectionError:
                targets_df.loc[site_index, 'Latest SAR Image'] = None

        targets_df = targets_df.sort_values('id')
    except NotImplementedError:
        targets_df = pd.DataFrame(columns=['Site',
                                           'Latest SAR Image',
                                           'Unrest'])
        targets_df.loc[0] = ["API Connection Error"] * 3
    return targets_df[['Site', 'Latest SAR Image', 'Unrest']]


def _read_coherence(coherence_csv):
    if coherence_csv is None:
        return None
    coh = pd.read_csv(
        coherence_csv,
        parse_dates=['Reference Date', 'Pair Date'])
    coh.columns = ['first_date', 'second_date', 'coherence']
    wrong_order = (coh.second_date < coh.first_date) & coh.coherence.notnull()
    if wrong_order.any():
        raise RuntimeError(
            'Some intereferogram dates not ordered as expected:\n'
            f'{coh[wrong_order].to_string()}'
        )
    return coh


def _read_insar_pair(insar_pair_csv):
    if insar_pair_csv is None:
        return None
    # Check if the file exists
    if not os.path.exists(insar_pair_csv):
        # raise FileNotFoundError(f"The file {insar_pair_csv} does not exist.")
        logger.info("The file %s does not exist.", insar_pair_csv)
        return None

    insar = pd.read_csv(
        insar_pair_csv,
        parse_dates=['Reference_Date', 'Pair_Date'])
    insar.columns = ['first_date', 'second_date', 'insar_pair']
    wrong_order = (
        (insar.second_date < insar.first_date) & insar.insar_pair.notnull()
    )
    if wrong_order.any():
        raise RuntimeError(
            'Some intereferogram dates not ordered as expected:\n'
            f'{insar[wrong_order].to_string()}'
        )
    return insar


def _read_baseline(baseline_csv):
    if baseline_csv is None:
        return None
    # Check if the file exists
    if not os.path.exists(baseline_csv):
        # raise FileNotFoundError(f"The file {insar_pair_csv} does not exist.")
        logger.info("The file %s does not exist.", baseline_csv)
        return None

    baseline = pd.read_csv(
        baseline_csv,
        delimiter=' ',
        header=None,
        skipinitialspace=True)
    baseline.columns = ['index',
                        'first_date',
                        'second_date',
                        'bperp',
                        'btemp',
                        'bperp2',
                        'x']
    baseline = baseline.drop(['index',
                              'btemp',
                              'bperp2',
                              'x'], axis=1)
    baseline['first_date'] = pd.to_datetime(baseline['first_date'],
                                            format="%Y%m%d")
    baseline['second_date'] = pd.to_datetime(baseline['second_date'],
                                             format="%Y%m%d")
    return baseline


def _valid_dates(coh):
    return coh.first_date.dropna().unique()


def _coherence_csv(target_id):
    if target_id == 'API Response Error':
        return None
    site, beam = target_id.rsplit('_', 1)
    return f'app/Data/{site}/{beam}/CoherenceMatrix.csv'


def _insar_pair_csv(target_id):
    if target_id == 'API Response Error':
        return None
    site, beam = target_id.rsplit('_', 1)
    return f'app/Data/{site}/{beam}/InSAR_Pair_All.csv'


def _baseline_csv(target_id):
    if target_id == 'API Response Error':
        return None
    site, beam = target_id.rsplit('_', 1)
    return f'app/Data/{site}/{beam}/bperp_all'


config = get_config_params()
