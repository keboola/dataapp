import streamlit as st
import pandas as pd
import json
import plotly.express as px
from keboola_streamlit import KeboolaStreamlit

# Initialize Keboola streamlit connector
keboola = KeboolaStreamlit(root_url=st.secrets['kbc_url'], token=st.secrets['kbc_token'])

# Set page configuration
st.set_page_config(page_title="Data Quality Dashboard", layout="wide")

@st.cache_data(show_spinner=True)
def get_table():
    # Read the data table from Keboola
    return keboola.read_table(st.secrets['DQ_TABLE_ID'])

# Cache data loading and processing

def load_and_process_data():
    # Read the data table from Keboola
    df = get_table()
    st.write(df)
    # Filter rows with JSON strings in the 'TEST_RESULT_VALUE' column
    def filter_conditions(value):
        return isinstance(value, str) and value.startswith('[{"OCCURRENCES"')

    df = df[df['TEST_RESULT_VALUE'].apply(filter_conditions)]

    # Parse 'TEST_QUERY' to extract 'TABLE', 'COLUMN', and 'CRITERIA'
    def parse_query(query):
        query_json = json.loads(query)
        if query_json.get('TABLE_NAME_MAIN', False):
            table = query_json.get('TABLE_NAME_MAIN')
        else:
            table = query_json.get('TABLE_NAME', '') 
        column = query_json.get('COLUMN_NAME', '')
        value = query_json.get('VALUE', '')
        return [table, column, value]

    df[['TABLE', 'COLUMN', 'CRITERIA']] = df['TEST_PARAMETERS'].apply(parse_query).apply(pd.Series)

    # Expand rows based on 'TEST_RESULT_VALUE'
    def expand_data(row):
        offenders = json.loads(row['TEST_RESULT_VALUE'])
        return [
            {
                'TABLE': row['TABLE'],
                'COLUMN': row['COLUMN'],
                'TEST_NAME': row['TEST_NAME'],
                'CRITERIA': row['CRITERIA'],
                'OFFENDERS': offender.get('OFFENDERS', ''),
                'OCCURRENCES': offender.get('OCCURRENCES', 0),
                'TEST_QUERY': row['TEST_QUERY']
            }
            for offender in offenders
        ]

    # Apply the expansion to each row and convert to a new DataFrame
    expanded_rows = df.apply(expand_data, axis=1).explode().reset_index(drop=True)
    return pd.DataFrame(expanded_rows.tolist())

# Load data into the DataFrame
df = load_and_process_data()

# Sidebar: Filters
st.sidebar.header("Filters")
selected_table = st.sidebar.multiselect("Select Table", df['TABLE'].unique())
selected_column = st.sidebar.multiselect("Select Column", df['COLUMN'].unique())
selected_test = st.sidebar.multiselect("Select Test Name", df['TEST_NAME'].unique())
selected_criteria = st.sidebar.multiselect("Select Criteria", df['CRITERIA'].unique())

# Reset Filters button
if st.sidebar.button("Reset Filters"):
    selected_table, selected_column, selected_test, selected_criteria = [], [], [], []

# Apply filters dynamically
if selected_table:
    df = df[df['TABLE'].isin(selected_table)]
if selected_column:
    df = df[df['COLUMN'].isin(selected_column)]
if selected_test:
    df = df[df['TEST_NAME'].isin(selected_test)]
if selected_criteria:
    df = df[df['CRITERIA'].isin(selected_criteria)]

# Initialize session state to track view mode
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "overview"  # Default to overview

# Main: Dashboard title
st.title("Data Quality Dashboard")

# Metrics: High-level overview
st.header("Data Quality Summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Issues", df['OCCURRENCES'].sum())
col2.metric("Unique Tables", df['TABLE'].nunique())
col3.metric("Unique Columns", df['COLUMN'].nunique())
col4.metric("Unique Tests", df['TEST_NAME'].nunique())

# Proportion of Issues by Test Name (toggle between overview and detail)
with st.container():
    if st.session_state.view_mode == "overview":
        st.subheader("Proportion of Issues by Test Name")
        test_occurrences = df.groupby('TEST_NAME')['OCCURRENCES'].sum().reset_index()
        test_occurrences['Total Percentage'] = test_occurrences['OCCURRENCES'] / test_occurrences['OCCURRENCES'].sum() * 100

        chart_type = st.radio("Chart Type", ['Pie Chart', 'Bar Chart'], key='chart_type')

        if chart_type == 'Pie Chart':
            fig = px.pie(test_occurrences, values='OCCURRENCES', names='TEST_NAME',
                         title="Proportion of Occurrences by Test Name",
                         color_discrete_sequence=px.colors.sequential.Oranges[::-1])
            st.plotly_chart(fig, use_container_width=True)
        else:
            fig = px.bar(test_occurrences, x='TEST_NAME', y='OCCURRENCES',
                         title="Occurrences by Test Name",
                         labels={'OCCURRENCES': 'Number of Occurrences', 'TEST_NAME': 'Test Name'},
                         color='TEST_NAME', color_discrete_sequence=px.colors.sequential.Oranges[::-1])
            st.plotly_chart(fig, use_container_width=True)

        # Detail button to switch to a detailed view
        if st.button("Detail"):
            st.session_state.view_mode = "detail"
            st.experimental_rerun()
    else:
        st.subheader("Detailed Proportion of Issues by Test Name (Split by Table and Column)")
        detailed_data = df.groupby(['TEST_NAME', 'TABLE', 'COLUMN'])['OCCURRENCES'].sum().reset_index()
        detailed_data['Total Percentage'] = detailed_data['OCCURRENCES'] / detailed_data['OCCURRENCES'].sum() * 100

        chart_type = st.radio("Chart Type", ['Pie Chart', 'Bar Chart'], key='detail_chart_type')

        if chart_type == 'Pie Chart':
            fig = px.pie(detailed_data, values='OCCURRENCES', names='TEST_NAME',
                         title="Detailed Occurrences by Test Name (Split by Table and Column)",
                         color_discrete_sequence=px.colors.sequential.Oranges[::-1],
                         facet_col='COLUMN', hover_data=['TABLE', 'COLUMN'])
            st.plotly_chart(fig, use_container_width=True)
        else:
            fig = px.bar(detailed_data, x='TEST_NAME', y='OCCURRENCES', color='TABLE',
                         title="Detailed Occurrences by Test Name (Split by Table and Column)",
                         labels={'OCCURRENCES': 'Number of Occurrences', 'TEST_NAME': 'Test Name'},
                         hover_data=['TABLE', 'COLUMN'],
                         color_discrete_sequence=px.colors.sequential.Oranges[::-1],
                         barmode='stack')
            st.plotly_chart(fig, use_container_width=True)

        # Back button to return to overview
        if st.button("Overview"):
            st.session_state.view_mode = "overview"
            st.experimental_rerun()

# Detailed Data Table (with filter option for granularity)
st.subheader("Detailed Data")
granularity = st.radio("Select Granularity", ['Summary', 'Detailed'])

if granularity == 'Summary':
    summary_df = df.groupby(['TABLE', 'COLUMN', 'TEST_NAME', 'CRITERIA']).agg({'OCCURRENCES': 'sum'}).reset_index()
    st.dataframe(summary_df, use_container_width=True)
else:
    st.dataframe(df, use_container_width=True)

# CSV download button
@st.cache_data
def convert_df_to_csv(df, granularity):
    if granularity == 'Summary':
        data_to_download = df.groupby(['TABLE', 'COLUMN', 'TEST_NAME', 'CRITERIA']).agg({'OCCURRENCES': 'sum'}).reset_index()
    else:
        data_to_download = df
    return data_to_download.to_csv(index=False).encode('utf-8')

# Create CSV and add download button
csv = convert_df_to_csv(df, granularity)
st.download_button(label="Download data as CSV", data=csv, file_name=f'{granularity}_data.csv', mime='text/csv')
