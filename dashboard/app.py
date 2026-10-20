import os
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Add project root to sys.path to enable core imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db_client import get_connection

st.set_page_config(
    page_title="JobHunterKit Funnel Dashboard",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Premium Sleek CSS Styling (Forces custom light theme)
st.markdown(
    """
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
    /* Main container and text overrides */
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #f4f6f9 !important;
        color: #0f172a !important;
        font-family: 'Outfit', sans-serif !important;
    }

    /* Remove Streamlit default header */
    [data-testid="stHeader"] {
        background-color: transparent !important;
    }

    /* Subheader and markdown fonts */
    h1, h2, h3, h4, h5, h6, .stMarkdown p {
        color: #0f172a !important;
        font-family: 'Outfit', sans-serif !important;
        font-weight: 600 !important;
    }

    /* Caption font styling */
    p[data-testid="stCaption"] {
        color: #64748b !important;
        font-size: 0.85rem !important;
        font-family: 'Outfit', sans-serif !important;
    }

    /* Premium Metric Cards - Light Theme styling */
    .metric-card {
        background: #ffffff !important;
        border-radius: 16px !important;
        padding: 24px !important;
        border: 1px solid rgba(0, 0, 0, 0.08) !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04) !important;
        text-align: center;
        transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
    }

    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(37, 99, 235, 0.4) !important;
        box-shadow: 0 10px 25px rgba(37, 99, 235, 0.08) !important;
    }

    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #2563eb;
    }

    .metric-label {
        font-size: 0.8rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    /* Expander card custom design */
    .streamlit-expanderHeader {
        background-color: #ffffff !important;
        border: 1px solid rgba(0, 0, 0, 0.08) !important;
        border-radius: 8px !important;
        color: #0f172a !important;
        font-weight: 600 !important;
    }

    .streamlit-expanderContent {
        background-color: #ffffff !important;
        border-left: 1px solid rgba(0, 0, 0, 0.05) !important;
        border-right: 1px solid rgba(0, 0, 0, 0.05) !important;
        border-bottom: 1px solid rgba(0, 0, 0, 0.05) !important;
        border-bottom-left-radius: 8px !important;
        border-bottom-right-radius: 8px !important;
        padding: 15px !important;
    }

    /* Table / Dataframe wrapper styling */
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(0, 0, 0, 0.08) !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        background-color: #ffffff !important;
    }

    /* Sidebar styling overrides */
    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid rgba(0, 0, 0, 0.08) !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


def render_highchart(container_id, options, height=350):
    """Render a Highcharts component via Streamlit."""
    import json

    options_str = json.dumps(options)
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://code.highcharts.com/highcharts.js"></script>
        <script src="https://code.highcharts.com/modules/funnel.js"></script>
        <script src="https://code.highcharts.com/highcharts-more.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                background-color: transparent;
                margin: 0;
                padding: 0;
                overflow: hidden;
            }}
            #chart-container {{
                width: 100%;
                height: {height}px;
            }}
        </style>
    </head>
    <body>
        <div id="chart-container"></div>
        <script>
            document.addEventListener("DOMContentLoaded", function() {{
                const options = {options_str};
                options.chart = options.chart || {{}};
                options.chart.backgroundColor = 'transparent';
                options.chart.style = options.chart.style || {{}};
                options.chart.style.fontFamily = "'Outfit', sans-serif";

                options.title = options.title || {{ text: null }};
                options.credits = {{ enabled: false }};

                if (options.xAxis) {{
                    if (Array.isArray(options.xAxis)) {{
                        options.xAxis.forEach(axis => {{
                            axis.gridLineColor = 'rgba(0, 0, 0, 0.05)';
                            axis.lineColor = 'rgba(0, 0, 0, 0.1)';
                            axis.tickColor = 'rgba(0, 0, 0, 0.1)';
                            axis.labels = axis.labels || {{}};
                            axis.labels.style = axis.labels.style || {{}};
                            axis.labels.style.color = '#64748b';
                        }});
                    }} else {{
                        options.xAxis.gridLineColor = 'rgba(0, 0, 0, 0.05)';
                        options.xAxis.lineColor = 'rgba(0, 0, 0, 0.1)';
                        options.xAxis.tickColor = 'rgba(0, 0, 0, 0.1)';
                        options.xAxis.labels = options.xAxis.labels || {{}};
                        options.xAxis.labels.style = options.xAxis.labels.style || {{}};
                        options.xAxis.labels.style.color = '#64748b';
                    }}
                }}

                if (options.yAxis) {{
                    if (Array.isArray(options.yAxis)) {{
                        options.yAxis.forEach(axis => {{
                            axis.gridLineColor = 'rgba(0, 0, 0, 0.05)';
                            axis.lineColor = 'rgba(0, 0, 0, 0.1)';
                            axis.labels = axis.labels || {{}};
                            axis.labels.style = axis.labels.style || {{}};
                            axis.labels.style.color = '#64748b';
                        }});
                    }} else {{
                        options.yAxis.gridLineColor = 'rgba(0, 0, 0, 0.05)';
                        options.yAxis.lineColor = 'rgba(0, 0, 0, 0.1)';
                        options.yAxis.labels = options.yAxis.labels || {{}};
                        options.yAxis.labels.style = options.yAxis.labels.style || {{}};
                        options.yAxis.labels.style.color = '#64748b';
                    }}
                }}

                if (options.legend) {{
                    options.legend.itemStyle = options.legend.itemStyle || {{}};
                    options.legend.itemStyle.color = '#1e293b';
                    options.legend.itemHoverStyle = options.legend.itemHoverStyle || {{}};
                    options.legend.itemHoverStyle.color = '#2563eb';
                }}

                Highcharts.chart('chart-container', options);
            }});
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=height)


@st.cache_data(ttl=60)
def load_dashboard_data():
    """Load jobs, scores, and applications data from the database."""
    conn = get_connection()

    # 1. Fetch jobs
    query_jobs = """
        SELECT id, title, company, location, source, scraped_at, status_score, status_apply, keyword, url
        FROM job_hunter.jobs
        ORDER BY scraped_at DESC;
    """
    df_jobs = pd.read_sql(query_jobs, conn)

    # 2. Fetch scores
    query_scores = """
        SELECT job_id, match_score, reasoning, scored_at
        FROM job_hunter.scores;
    """
    df_scores = pd.read_sql(query_scores, conn)

    # 3. Fetch applications
    query_apps = """
        SELECT job_id, status, applied_at, error_message
        FROM job_hunter.applications;
    """
    df_apps = pd.read_sql(query_apps, conn)

    conn.close()
    return df_jobs, df_scores, df_apps


try:
    df_jobs, df_scores, df_apps = load_dashboard_data()
    data_loaded = True
except Exception as e:
    st.error(f"Failed to connect to the Supabase database: {e}")
    data_loaded = False

if data_loaded:
    st.title("💼 Job Funnel Dashboard")
    st.markdown("Track scraped jobs, match quality, and automated submission statuses.")

    # Apply base filters early (needed for calculations)
    # Temporary placeholder values for variables defined later in sidebar/columns
    # Streamlit rerun flow handles this, but to resolve name scoping, we declare them here:
    selected_source = "All"
    selected_keyword = "All"

    # We will build columns first to capture inputs
    col_content, col_sidebar = st.columns([3, 1])

    with col_sidebar:
        with st.expander("⚙️ Dashboard Filters", expanded=False):
            all_sources = ["All"] + list(df_jobs["source"].dropna().unique())
            selected_source = st.selectbox(
                "Filter by Source", all_sources, key="filter_src"
            )

            all_keywords = ["All"] + list(df_jobs["keyword"].dropna().unique())
            selected_keyword = st.selectbox(
                "Filter by Keyword", all_keywords, key="filter_kw"
            )

            st.markdown("---")
            st.markdown("**Table Filters**")

            # 1. Filter by ATS Score Range
            min_score = st.slider(
                "Min Match Score",
                min_value=0,
                max_value=100,
                value=0,
                key="filter_score",
            )

            # 2. Filter by Apply Status
            all_statuses = ["Pending"] + list(df_apps["status"].dropna().unique())
            selected_statuses = st.multiselect(
                "Filter by Status",
                all_statuses,
                default=all_statuses,
                key="filter_status",
            )

            # 3. Action-required Quick Filter
            only_show_manual = st.checkbox(
                "⚠️ Show Action Required Only", value=False, key="filter_manual"
            )

    # Apply filters based on selected inputs
    filtered_jobs = df_jobs.copy()
    if selected_source != "All":
        filtered_jobs = filtered_jobs[filtered_jobs["source"] == selected_source]
    if selected_keyword != "All":
        filtered_jobs = filtered_jobs[filtered_jobs["keyword"] == selected_keyword]

    filtered_scores = df_scores[df_scores["job_id"].isin(filtered_jobs["id"])]
    filtered_apps = df_apps[df_apps["job_id"].isin(filtered_jobs["id"])]

    # Pre-build explorer dataframe early for warning metrics and sidebar Hot Leads
    df_explorer = filtered_jobs.merge(
        filtered_scores[["job_id", "match_score", "reasoning"]],
        left_on="id",
        right_on="job_id",
        how="left",
    ).merge(
        filtered_apps[["job_id", "status", "error_message"]],
        left_on="id",
        right_on="job_id",
        how="left",
    )

    # Enhancement 1: Top warning alert badge for "Action Required"
    action_required_statuses = [
        "manual_required",
        "manual_intervention",
        "failed",
        "failed_form",
        "action_required",
    ]
    df_manual = df_explorer[
        df_explorer["status"].str.lower().isin(action_required_statuses)
        | df_explorer["status"].str.lower().str.contains("manual", na=False)
    ]
    manual_required_count = len(df_manual)

    # (Warning alert rendering is moved inside col_content below)

    # Render Top Matches in the sidebar col_sidebar
    with col_sidebar:
        with st.expander("🔥 Top Matches (Score >= 85)", expanded=False):
            df_leads = (
                df_explorer[df_explorer["match_score"] >= 85]
                .sort_values(by="match_score", ascending=False)
                .head(5)
            )
            if not df_leads.empty:
                for idx, row in df_leads.iterrows():
                    job_url = row.get("url", "#")
                    st.markdown(
                        f'<div style="font-size: 0.85rem; line-height: 1.4; margin-bottom: 8px; color: #0f172a;">'
                        f'🎯 <b style="color: #2563eb;">{int(row["match_score"])}%</b> - {row["title"]}<br>'
                        f'<span style="color: #64748b;">{row["company"]} ({row["location"]})</span><br>'
                        f'<a href="{job_url}" target="_blank" style="color: #2563eb; '
                        f'text-decoration: none; font-weight: 600; font-size: 0.8rem;">View Posting</a>'
                        f"</div>"
                        f'<hr style="margin: 6px 0; border: 0; border-top: 1px solid rgba(0,0,0,0.06);">',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No hot leads found with score >= 85.")

    total_jobs = len(filtered_jobs)

    # Put all main charts inside the left-side column col_content
    with col_content:
        # Pre-calculate metrics needed for funnel and telemetry cards
        scored_jobs = len(filtered_jobs[filtered_jobs["status_score"] == "completed"])
        passed_jobs = len(filtered_scores[filtered_scores["match_score"] >= 70])
        applied_jobs = len(filtered_apps)
        success_apps = len(
            filtered_apps[
                filtered_apps["status"].str.contains(
                    "Success|Submitted", case=False, na=False
                )
            ]
        )

        # Enhancement 1: Top warning alert badge for "Action Required"
        if manual_required_count > 0:
            st.warning(
                f"⚠️ **Action Required**: You have **{manual_required_count}** applications waiting "
                f"for manual intervention. Please check the data explorer below or check the box "
                f"in the sidebar to complete them."
            )

        # Pipeline Telemetry Metrics Cards
        st.subheader("📊 Pipeline Telemetry")
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.markdown(
                f'<div class="metric-card"><div class="metric-value">{total_jobs}</div>'
                f'<div class="metric-label">Jobs Scraped</div></div>',
                unsafe_allow_html=True,
            )
        with col_m2:
            pass_rate = (passed_jobs / scored_jobs * 100) if scored_jobs > 0 else 0
            st.markdown(
                f'<div class="metric-card"><div class="metric-value">{pass_rate:.1f}%</div>'
                f'<div class="metric-label">AI Match Pass Rate</div></div>',
                unsafe_allow_html=True,
            )
        with col_m3:
            st.markdown(
                f'<div class="metric-card"><div class="metric-value">{applied_jobs}</div>'
                f'<div class="metric-label">Jobs Applied</div></div>',
                unsafe_allow_html=True,
            )
        with col_m4:
            st.markdown(
                f'<div class="metric-card"><div class="metric-value">{manual_required_count}</div>'
                f'<div class="metric-label">Manual Actions</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # 2. Funnel metrics
        st.subheader("📊 Funnel Conversions")
        st.caption(
            "Drop-offs represent jobs filtered out by anti-bot checks, salary criteria, or matching score filters."
        )

        funnel_options = {
            "chart": {"type": "funnel", "marginRight": 100},
            "tooltip": {
                "headerFormat": '<span style="font-size: 10px; color: #64748b">{point.key}</span><br/>',
                "pointFormat": "● Count: <b>{point.y}</b><br/>",
            },
            "plotOptions": {
                "series": {
                    "dataLabels": {
                        "enabled": True,
                        "format": "<b>{point.name}</b> ({point.y:,.0f})",
                        "color": "#1e293b",
                        "softConnector": True,
                        "style": {"textOutline": "none"},
                    },
                    "center": ["40%", "50%"],
                    "neckWidth": "30%",
                    "neckHeight": "25%",
                    "width": "80%",
                }
            },
            "legend": {"enabled": False},
            "series": [
                {
                    "name": "Jobs",
                    "data": [
                        ["Scraped", total_jobs],
                        ["Scored (LLM)", scored_jobs],
                        ["Passed (>=70)", passed_jobs],
                        ["Applied", applied_jobs],
                        ["Success", success_apps],
                    ],
                    "colors": ["#2563eb", "#3b82f6", "#60a5fa", "#818cf8", "#a78bfa"],
                }
            ],
        }
        render_highchart("conversion_funnel", funnel_options, height=400)

        # 3. Score Distribution & Donut Chart
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("📈 Match Quality & Status Breakdown")
        st.caption(
            "Review how jobs align with your CV (left) and the current state of the database queue (right)."
        )

        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.markdown("**AI Match Scores**")
            active_scores = filtered_scores[filtered_scores["match_score"] > 0]
            if not active_scores.empty:
                score_counts = active_scores["match_score"].value_counts().sort_index()
                categories = [str(x) for x in score_counts.index]
                data_values = [int(x) for x in score_counts.values]

                score_chart_options = {
                    "chart": {"type": "column"},
                    "xAxis": {
                        "categories": categories,
                        "title": {"text": "ATS Score", "style": {"color": "#64748b"}},
                    },
                    "yAxis": {
                        "title": {"text": "Count", "style": {"color": "#64748b"}}
                    },
                    "legend": {"enabled": False},
                    "plotOptions": {
                        "column": {
                            "borderRadius": 4,
                            "borderWidth": 0,
                            "colors": [
                                {
                                    "linearGradient": {
                                        "x1": 0,
                                        "y1": 0,
                                        "x2": 0,
                                        "y2": 1,
                                    },
                                    "stops": [[0, "#2563eb"], [1, "#60a5fa"]],
                                }
                            ],
                            "colorByPoint": True,
                        }
                    },
                    "series": [{"name": "Jobs Count", "data": data_values}],
                }
                render_highchart("score_histogram", score_chart_options, height=300)
            else:
                st.info("No score data available for selected filters.")

        with col_chart2:
            st.markdown("**Queue Statuses**")
            if not filtered_apps.empty:
                app_status_counts = filtered_apps["status"].value_counts()
                pie_data = [
                    {"name": str(status), "y": int(count)}
                    for status, count in app_status_counts.items()
                ]

                pie_options = {
                    "chart": {"type": "pie"},
                    "tooltip": {
                        "pointFormat": "{series.name}: <b>{point.percentage:.1f}%</b> (Count: {point.y})"
                    },
                    "accessibility": {
                        "point": {
                            "valueDescriptionFormat": "{index}. {point.name}: {point.y:,.0f}."
                        }
                    },
                    "plotOptions": {
                        "pie": {
                            "allowPointSelect": True,
                            "cursor": "pointer",
                            "dataLabels": {
                                "enabled": True,
                                "format": "<b>{point.name}</b>: {point.percentage:.1f}%",
                                "color": "#1e293b",
                                "style": {
                                    "textOutline": "none",
                                    "fontFamily": "'Outfit', sans-serif",
                                },
                            },
                        }
                    },
                    "series": [
                        {
                            "name": "Status Share",
                            "colorByPoint": True,
                            "data": pie_data,
                            "colors": [
                                "#3b82f6",
                                "#10b981",
                                "#ef4444",
                                "#f59e0b",
                                "#6366f1",
                                "#ec4899",
                            ],
                        }
                    ],
                }
                render_highchart("queue_statuses_pie", pie_options, height=300)
            else:
                st.info("No application data available for selected filters.")

        # 4. Daily Volume Trend
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("📅 Daily Funnel Activity")
        st.caption("Daily volume of scraped, scored, and submitted jobs.")

        # Process daily trends
        if not filtered_jobs.empty:
            filtered_jobs["date"] = pd.to_datetime(filtered_jobs["scraped_at"]).dt.date
            daily_scraped = filtered_jobs.groupby("date").size().rename("Scraped")

            daily_trend = pd.DataFrame(daily_scraped)

            if not filtered_scores.empty:
                filtered_scores["date"] = pd.to_datetime(
                    filtered_scores["scored_at"]
                ).dt.date
                daily_scored = filtered_scores.groupby("date").size().rename("Scored")
                daily_trend = daily_trend.join(daily_scored, how="outer")

            if not filtered_apps.empty:
                filtered_apps["date"] = pd.to_datetime(
                    filtered_apps["applied_at"]
                ).dt.date
                daily_applied = filtered_apps.groupby("date").size().rename("Applied")
                daily_trend = daily_trend.join(daily_applied, how="outer")

            daily_trend = daily_trend.fillna(0).astype(int)

            # Prepare Highcharts AreaSpline Chart
            trend_dates = [str(x) for x in daily_trend.index]
            scraped_vals = [
                int(x)
                for x in daily_trend.get(
                    "Scraped", pd.Series([0] * len(daily_trend))
                ).values
            ]
            scored_vals = [
                int(x)
                for x in daily_trend.get(
                    "Scored", pd.Series([0] * len(daily_trend))
                ).values
            ]
            applied_vals = [
                int(x)
                for x in daily_trend.get(
                    "Applied", pd.Series([0] * len(daily_trend))
                ).values
            ]

            trend_options = {
                "chart": {"type": "areaspline"},
                "xAxis": {
                    "categories": trend_dates,
                    "title": {"text": "Date", "style": {"color": "#64748b"}},
                },
                "yAxis": {"title": {"text": "Volume", "style": {"color": "#64748b"}}},
                "plotOptions": {
                    "areaspline": {
                        "fillOpacity": 0.1,
                        "marker": {"enabled": True, "radius": 4, "symbol": "circle"},
                    }
                },
                "series": [
                    {"name": "Scraped", "data": scraped_vals, "color": "#2563eb"},
                    {"name": "Scored", "data": scored_vals, "color": "#06b6d4"},
                    {"name": "Applied", "data": applied_vals, "color": "#d946ef"},
                ],
            }
            render_highchart("daily_trend", trend_options, height=350)
        else:
            st.info("No timeline data available.")

    # 5. Data Explorer Table (Full-width, outside col_content)
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🔍 Applications Tracker")
    st.caption(
        "Search, sort, and click 'View Posting' to open a job page. Review AI reasoning for match score details."
    )

    # Column-level search filters row aligned with the table columns
    col_t1, col_t2, col_t3, col_t4, col_t5, col_t6, col_t7, col_t8, col_t9, col_t10 = (
        st.columns([3.1, 2.3, 2.3, 1.7, 1.6, 2.1, 1.9, 2.1, 3.6, 2.1])
    )
    with col_t1:
        search_title = st.text_input(
            "Filter Title",
            placeholder="Filter Title...",
            label_visibility="collapsed",
            key="search_title",
        )
    with col_t2:
        search_company = st.text_input(
            "Filter Company",
            placeholder="Filter Company...",
            label_visibility="collapsed",
            key="search_company",
        )
    with col_t3:
        search_location = st.text_input(
            "Filter Location",
            placeholder="Filter Location...",
            label_visibility="collapsed",
            key="search_location",
        )

    # Keep and rename columns for display
    display_cols = {
        "title": "Title",
        "company": "Company",
        "location": "Location",
        "scraped_at": "Date Scraped",
        "source": "Source",
        "match_score": "ATS Score",
        "status_score": "Score State",
        "status": "Apply Status",
        "reasoning": "AI Reasoning",
        "url": "Job Link",
    }
    df_display = df_explorer[list(display_cols.keys())].rename(columns=display_cols)
    df_display["Date Scraped"] = pd.to_datetime(
        df_display["Date Scraped"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    def format_score(val):
        """Format the score value to a string."""
        if pd.isna(val) or val == "N/A" or val == "":
            return "N/A"
        try:
            return str(int(float(val)))
        except (ValueError, TypeError):
            return str(val)

    df_display["ATS Score"] = df_display["ATS Score"].apply(format_score)
    df_display["Apply Status"] = (
        df_display["Apply Status"].fillna("Pending").astype(str)
    )

    # Filter display dataframe based on sidebar selections
    df_filtered_display = df_display.copy()

    if only_show_manual:
        df_filtered_display = df_filtered_display[
            df_filtered_display["Apply Status"]
            .str.lower()
            .isin(action_required_statuses)
            | df_filtered_display["Apply Status"]
            .str.lower()
            .str.contains("manual", na=False)
        ]
    else:
        if min_score > 0:
            # Convert ATS Score to numeric for filtering
            df_filtered_display["score_num"] = pd.to_numeric(
                df_filtered_display["ATS Score"], errors="coerce"
            ).fillna(0)
            df_filtered_display = df_filtered_display[
                df_filtered_display["score_num"] >= min_score
            ]
            df_filtered_display = df_filtered_display.drop(columns=["score_num"])

        if selected_statuses:
            df_filtered_display = df_filtered_display[
                df_filtered_display["Apply Status"].isin(selected_statuses)
            ]

    # Apply column-level search queries if provided
    if search_title:
        df_filtered_display = df_filtered_display[
            df_filtered_display["Title"].str.contains(
                search_title, case=False, na=False
            )
        ]
    if search_company:
        df_filtered_display = df_filtered_display[
            df_filtered_display["Company"].str.contains(
                search_company, case=False, na=False
            )
        ]
    if search_location:
        df_filtered_display = df_filtered_display[
            df_filtered_display["Location"].str.contains(
                search_location, case=False, na=False
            )
        ]

    # Format ATS Score as numeric for progress bar config
    df_filtered_display["ATS Score"] = (
        pd.to_numeric(df_filtered_display["ATS Score"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    st.dataframe(
        df_filtered_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ATS Score": st.column_config.ProgressColumn(
                "ATS Score",
                help="Gemini match score matching your CV to the job description",
                min_value=0,
                max_value=100,
                format="%d%%",
            ),
            "Job Link": st.column_config.LinkColumn(
                "Job Link",
                help="Click to open job posting",
                validate=r"^https?://",
                max_chars=100,
                display_text="View Posting",
            ),
        },
    )
