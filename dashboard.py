import streamlit as st
import requests
import os
import tempfile
import math
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
load_dotenv()

st.set_page_config(page_title="Dashboard", page_icon="🎬", layout="wide")

# ============================
# PASSWORD PROTECTION
# ============================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("## 🔒 Dashboard Login")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == st.secrets.get("DASHBOARD_PASSWORD", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

st.title("Dashboard")
st.caption("")

tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🎁 Patreon", "📺 YouTube"])

# ============================
# FETCH DATA
# ============================

@st.cache_data(ttl=300)
def fetch_patreon_data():
    token = os.getenv("PATREON_ACCESS_TOKEN")
    campaign_id = "3563344"
    headers = {"Authorization": f"Bearer {token}"}
    all_members = []
    all_included = []
    cursor = None
    while True:
        params = {
            "fields[member]": "full_name,patron_status,currently_entitled_amount_cents,lifetime_support_cents,campaign_lifetime_support_cents,last_charge_status,last_charge_date,pledge_relationship_start,will_pay_amount_cents,is_follower,pledge_cadence",
            "include": "currently_entitled_tiers",
            "fields[tier]": "title,amount_cents",
            "page[count]": 1000
        }
        if cursor:
            params["page[cursor]"] = cursor
        resp = requests.get(
            f"https://www.patreon.com/api/oauth2/v2/campaigns/{campaign_id}/members",
            headers=headers, params=params
        ).json()
        all_members.extend(resp.get("data", []))
        all_included.extend(resp.get("included", []))
        next_cursor = resp.get("meta", {}).get("pagination", {}).get("cursors", {}).get("next")
        if not next_cursor:
            break
        cursor = next_cursor
    return {"data": all_members, "included": all_included}

@st.cache_data(ttl=300)
def fetch_youtube_data():
    api_key = os.getenv("YOUTUBE_API_KEY")
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID")
    channel_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "statistics,snippet,contentDetails", "id": channel_id, "key": api_key}
    ).json()
    channel = channel_resp["items"][0]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    videos = []
    next_page_token = None
    while True:
        params = {"part": "snippet", "playlistId": uploads_playlist, "maxResults": 50, "key": api_key}
        if next_page_token:
            params["pageToken"] = next_page_token
        playlist_resp = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", params=params).json()
        videos.extend(playlist_resp.get("items", []))
        next_page_token = playlist_resp.get("nextPageToken")
        if not next_page_token:
            break
    video_ids = [v["snippet"]["resourceId"]["videoId"] for v in videos]
    video_stats = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics,snippet", "id": ",".join(batch), "key": api_key}
        ).json()
        video_stats.extend(stats_resp.get("items", []))
    return channel, video_stats

def get_google_creds():
    """Load Google credentials from Streamlit secrets (cloud) or local file."""
    if "GOOGLE_CREDS" in st.secrets:
        creds_data = st.secrets["GOOGLE_CREDS"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(creds_data)
            tmp_path = f.name
        return Credentials.from_authorized_user_file(tmp_path)
    elif os.path.exists("google_creds.json"):
        return Credentials.from_authorized_user_file("google_creds.json")
    else:
        return None

@st.cache_data(ttl=300)
def fetch_youtube_analytics():
    try:
        creds = get_google_creds()
        if creds is None:
            return None
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        today = datetime.today()
        start_date = (today.replace(day=1) - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        response = youtube_analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,subscribersGained,subscribersLost,estimatedMinutesWatched",
            dimensions="day",
            sort="day"
        ).execute()
        rows = response.get("rows", [])
        df = pd.DataFrame(rows, columns=["Date", "Views", "Subs Gained", "Subs Lost", "Watch Time (mins)"])
        df["Date"] = pd.to_datetime(df["Date"])
        df["Net Subscribers"] = df["Subs Gained"] - df["Subs Lost"]
        return df
    except Exception as e:
        st.warning(f"YouTube Analytics error: {e}")
        return None

@st.cache_data(ttl=300)
def fetch_adsense_monthly():
    try:
        creds = get_google_creds()
        if creds is None:
            return {}
        service = build("adsense", "v2", credentials=creds)
        accounts = service.accounts().list().execute()
        if not accounts.get("accounts"):
            return {}
        account = accounts["accounts"][0]["name"]
        today = datetime.today()
        start = (today.replace(day=1) - timedelta(days=365))
        report = service.accounts().reports().generate(
            account=account,
            startDate={"year": start.year, "month": start.month, "day": 1},
            endDate={"year": today.year, "month": today.month, "day": today.day},
            metrics=["ESTIMATED_EARNINGS"],
            dimensions=["MONTH"]
        ).execute()
        monthly = {}
        for row in report.get("rows", []):
            month_str = row["cells"][0]["value"]
            earnings = float(row["cells"][1]["value"])
            monthly[month_str] = earnings
        return monthly
    except Exception:
        return {}

with st.spinner("Loading your data..."):
    members_resp = fetch_patreon_data()
    channel, video_stats = fetch_youtube_data()
    analytics_df = fetch_youtube_analytics()
    adsense_monthly = fetch_adsense_monthly()

# ============================
# PROCESS PATREON
# ============================

members = members_resp.get("data", [])
included = members_resp.get("included", [])

tier_map = {}
for item in included:
    if item.get("type") == "tier":
        tier_map[item["id"]] = item["attributes"].get("title", "Unknown")

for m in members:
    tier_ids = [t["id"] for t in m.get("relationships", {}).get("currently_entitled_tiers", {}).get("data", [])]
    m["tier"] = tier_map.get(tier_ids[0], "No Tier") if tier_ids else "No Tier"

def monthly_amount(m):
    amount = m["attributes"].get("currently_entitled_amount_cents", 0)
    cadence = m["attributes"].get("pledge_cadence", 1)
    if cadence == 12:
        return amount / 12 / 100
    return amount / 100

active = [m for m in members if m["attributes"].get("patron_status") == "active_patron"]
declined = [m for m in members if m["attributes"].get("patron_status") == "declined_patron"]
former = [m for m in members if m["attributes"].get("patron_status") == "former_patron"]
followers = [m for m in members if m["attributes"].get("is_follower")]
paid_active = [m for m in active if m["attributes"].get("currently_entitled_amount_cents", 0) > 0]

annual_active = [m for m in paid_active if m["attributes"].get("pledge_cadence", 1) == 12]
monthly_active = [m for m in paid_active if m["attributes"].get("pledge_cadence", 1) != 12]
avg_annual_sub = (sum(monthly_amount(m) for m in annual_active) / len(annual_active)) if annual_active else 0
avg_monthly_sub = (sum(monthly_amount(m) for m in monthly_active) / len(monthly_active)) if monthly_active else 0

monthly_revenue = sum(monthly_amount(m) for m in active)
lifetime_revenue = sum(m["attributes"].get("campaign_lifetime_support_cents", 0) for m in members) / 100
next_month_rev = sum(m["attributes"].get("will_pay_amount_cents", 0) for m in active) / 100

today = datetime.now(ZoneInfo("America/New_York"))
this_month = today.month
this_year = today.year
last_month = (today.replace(day=1) - timedelta(days=1)).month
last_month_year = (today.replace(day=1) - timedelta(days=1)).year

def patreon_revenue_for(year, month):
    total = 0
    for m in members:
        lc = m["attributes"].get("last_charge_date", "")
        ls = m["attributes"].get("last_charge_status", "")
        if lc and ls == "Paid":
            d = pd.to_datetime(lc[:10])
            if d.year == year and d.month == month:
                total += monthly_amount(m)
    return total

patreon_this_month = patreon_revenue_for(this_year, this_month)
patreon_last_month = patreon_revenue_for(last_month_year, last_month)
patreon_delta = patreon_this_month - patreon_last_month

patron_records = []
for m in members:
    start = m["attributes"].get("pledge_relationship_start")
    if start:
        patron_records.append({
            "Date": pd.to_datetime(start[:10]),
            "Tier": m.get("tier", "No Tier"),
            "Amount": monthly_amount(m),
            "Status": m["attributes"].get("patron_status"),
            "Cadence": m["attributes"].get("pledge_cadence", 1)
        })
patron_df = pd.DataFrame(patron_records) if patron_records else pd.DataFrame()

def signups_for(year, month, paid_only=True, through_day=None):
    if patron_df.empty:
        return 0
    df = patron_df[patron_df["Amount"] > 0] if paid_only else patron_df
    mask = (df["Date"].dt.year == year) & (df["Date"].dt.month == month)
    if through_day is not None:
        mask &= df["Date"].dt.day <= through_day
    return len(df[mask])

signups_this_month = signups_for(this_year, this_month)
signups_last_month = signups_for(last_month_year, last_month)
# MTD comparison: same day-of-month last month
signups_last_mtd = signups_for(last_month_year, last_month, through_day=today.day)
signups_mtd_delta = signups_this_month - signups_last_mtd
signups_delta = signups_this_month - signups_last_month

def cancellations_for(year, month):
    total = 0
    for m in members:
        if m["attributes"].get("patron_status") in ("former_patron", "declined_patron"):
            lc = m["attributes"].get("last_charge_date", "")
            if lc:
                d = pd.to_datetime(lc[:10])
                if d.year == year and d.month == month:
                    total += 1
    return total

cancel_this_month = cancellations_for(this_year, this_month)
cancel_last_month = cancellations_for(last_month_year, last_month)
cancel_delta = cancel_this_month - cancel_last_month

net_growth_this_month = signups_this_month - cancel_this_month

# Average member tenure in months (paid active members only)
tenure_months_list = []
for m in paid_active:
    start = m["attributes"].get("pledge_relationship_start")
    if start:
        start_dt = pd.to_datetime(start[:10])
        months = (today.year - start_dt.year) * 12 + (today.month - start_dt.month)
        tenure_months_list.append(months)
avg_tenure_months = round(sum(tenure_months_list) / len(tenure_months_list)) if tenure_months_list else 0

# Revenue from new subscribers (tab2: rolling 7 days)
new_rev_this_month = 0
new_rev_this_week = 0
if not patron_df.empty:
    active_df = patron_df[patron_df["Status"] == "active_patron"]
    month_new = active_df[(active_df["Date"].dt.year == this_year) & (active_df["Date"].dt.month == this_month)]
    new_rev_this_month = month_new["Amount"].sum()
    last_7_dates = set(today.date() - timedelta(days=i) for i in range(7))
    week_new = active_df[active_df["Date"].dt.date.isin(last_7_dates)]
    new_rev_this_week = week_new["Amount"].sum()

# New subs this calendar week (Sunday–Saturday)
days_since_sunday = (today.weekday() + 1) % 7
week_sunday = today.date() - timedelta(days=days_since_sunday)
week_saturday = week_sunday + timedelta(days=6)
dashboard_week_subs = 0
dashboard_week_rev = 0
if not patron_df.empty:
    paid_df = patron_df[patron_df["Amount"] > 0]
    cal_week = paid_df[(paid_df["Date"].dt.date >= week_sunday) & (paid_df["Date"].dt.date <= week_saturday)]
    dashboard_week_subs = len(cal_week)
    dashboard_week_rev = cal_week["Amount"].sum()

# ============================
# PROCESS YOUTUBE
# ============================

yt_stats = channel["statistics"]
subscribers = int(yt_stats["subscriberCount"])
total_views = int(yt_stats["viewCount"])
video_count = int(yt_stats["videoCount"])

videos_data = []
for v in video_stats:
    stats = v.get("statistics", {})
    snippet = v.get("snippet", {})
    videos_data.append({
        "Title": snippet.get("title", ""),
        "Published": snippet.get("publishedAt", "")[:10],
        "Views": int(stats.get("viewCount", 0)),
        "Likes": int(stats.get("likeCount", 0)),
        "Comments": int(stats.get("commentCount", 0)),
    })
videos_df = pd.DataFrame(videos_data).sort_values("Views", ascending=False) if videos_data else pd.DataFrame()

yt_views_this = yt_views_last = yt_views_avg = 0
yt_subs_this = yt_subs_last = yt_subs_avg = 0

if analytics_df is not None and not analytics_df.empty:
    monthly_yt = analytics_df.copy()
    monthly_yt["Month"] = monthly_yt["Date"].dt.to_period("M")
    monthly_agg = monthly_yt.groupby("Month")[["Views", "Net Subscribers"]].sum()

    this_period = pd.Period(f"{this_year}-{this_month:02d}", freq="M")
    last_period = pd.Period(f"{last_month_year}-{last_month:02d}", freq="M")

    yt_views_this = int(monthly_agg.loc[this_period, "Views"]) if this_period in monthly_agg.index else 0
    yt_views_last = int(monthly_agg.loc[last_period, "Views"]) if last_period in monthly_agg.index else 0
    yt_views_avg = int(monthly_agg["Views"].mean()) if not monthly_agg.empty else 0

    yt_subs_this = int(monthly_agg.loc[this_period, "Net Subscribers"]) if this_period in monthly_agg.index else 0
    yt_subs_last = int(monthly_agg.loc[last_period, "Net Subscribers"]) if last_period in monthly_agg.index else 0
    yt_subs_avg = int(monthly_agg["Net Subscribers"].mean()) if not monthly_agg.empty else 0

this_month_key = f"{this_year}-{this_month:02d}"
last_month_key = f"{last_month_year}-{last_month:02d}"
adsense_this = adsense_monthly.get(this_month_key, 0.0)
adsense_last = adsense_monthly.get(last_month_key, 0.0)
adsense_avg = round(sum(adsense_monthly.values()) / len(adsense_monthly), 2) if adsense_monthly else 0.0
adsense_delta = adsense_this - adsense_last

# ============================
# TIER TABLE HELPER
# ============================

TIER_ORDER = ["Free", "Lil Bestie", "Bestie", "Big Bestie", "Yuge Bestie", "Biggest Bestie", "You Stan Too Hard", "Literally God", "No Tier"]

def make_tier_table(df, period_col, period_values, period_label):
    if df.empty:
        return pd.DataFrame()
    existing_tiers = df["Tier"].unique().tolist()
    ordered_tiers = [t for t in TIER_ORDER if t in existing_tiers]
    remaining = [t for t in existing_tiers if t not in TIER_ORDER]
    tiers = ordered_tiers + remaining
    rows = []
    for period in period_values:
        row = {period_label: str(period)}
        period_data = df[df[period_col] == period]
        for tier in tiers:
            row[tier] = len(period_data[period_data["Tier"] == tier])
        row["Total"] = len(period_data)
        row["Revenue"] = round(period_data["Amount"].sum(), 2)
        row["Monthly Sub Rev"] = round(period_data[period_data["Cadence"] != 12]["Amount"].sum(), 2)
        row["Annual Sub Rev"] = round(period_data[period_data["Cadence"] == 12]["Amount"].sum(), 2)
        rows.append(row)
    total_row = {period_label: "TOTAL"}
    for tier in tiers:
        total_row[tier] = len(df[df["Tier"] == tier])
    total_row["Total"] = len(df)
    total_row["Revenue"] = round(df["Amount"].sum(), 2)
    total_row["Monthly Sub Rev"] = round(df[df["Cadence"] != 12]["Amount"].sum(), 2)
    total_row["Annual Sub Rev"] = round(df[df["Cadence"] == 12]["Amount"].sum(), 2)
    rows.append(total_row)
    return pd.DataFrame(rows)

# ============================
# TAB 1: DASHBOARD
# ============================

with tab1:
    st.subheader("Adsense")

    col1, col2, col3 = st.columns(3)
    col1.metric("This Month", f"${adsense_this:.2f}", delta=f"${adsense_delta:+.2f} vs last month", delta_color="normal")
    col2.metric("Last Month", f"${adsense_last:.2f}")
    col3.metric("12-Month Avg", f"${adsense_avg:.2f}")

    st.divider()

    st.subheader("Patreon")
    col1, col2, col3 = st.columns(3)
    col1.metric("Monthly Revenue", f"${math.ceil(monthly_revenue):,}")
    col2.metric("New Subs This Week", dashboard_week_subs)
    col3.metric("New Sub Revenue This Week", f"${dashboard_week_rev:.2f}")

    st.divider()

    st.subheader("Views")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month", f"{yt_views_this:,}", delta=f"{yt_views_this - yt_views_last:+,} vs last month", delta_color="normal")
    col2.metric("Last Month", f"{yt_views_last:,}")
    col3.metric("12-Month Avg", f"{yt_views_avg:,}")

    st.divider()

    st.subheader("Subscribers")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month (Net)", f"{yt_subs_this:+,}", delta=f"{yt_subs_this - yt_subs_last:+,} vs last month", delta_color="normal")
    col2.metric("Last Month (Net)", f"{yt_subs_last:+,}")
    col3.metric("12-Month Avg (Net)", f"{yt_subs_avg:+,}")

# ============================
# TAB 2: PATREON
# ============================

with tab2:
    st.subheader("Paid Members")

    col1, col2, col3 = st.columns(3)
    col1.metric("Paid Members", len(paid_active))
    col2.metric("Avg Monthly Sub", f"${avg_monthly_sub:,.2f}")
    col3.metric("Net Growth This Month", f"{net_growth_this_month:+}")

    st.divider()
    st.subheader("Paid Sign Ups")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Signups This Month", signups_this_month, delta=f"{signups_mtd_delta:+} vs last month (day {today.day})", delta_color="normal")
    col2.metric("Signups Last Month", signups_last_month)
    col3.metric("Cancellations This Month", cancel_this_month, delta=f"{cancel_delta:+} vs last month", delta_color="inverse")
    col4.metric("Cancellations Last Month", cancel_last_month)

    st.divider()
    st.subheader("Revenue")

    col1, col2, col3 = st.columns(3)
    col1.metric("Monthly Revenue", f"${math.ceil(monthly_revenue):,}")
    col2.metric("New Sub Revenue Past 7 Days", f"${math.ceil(new_rev_this_week):,}")
    col3.metric("New Sub Revenue This Month", f"${math.ceil(new_rev_this_month):,}")

    if not patron_df.empty:
        st.divider()

        highlight = ["Total", "Revenue"]

        col_weekly, _ = st.columns([1, 1])
        with col_weekly:
            st.subheader("New Members This Week")
            last_7 = [today.date() - timedelta(days=i) for i in range(6, -1, -1)]
            patron_df["DateOnly"] = patron_df["Date"].dt.date
            weekly_subset = patron_df[patron_df["DateOnly"].isin(last_7)]
            weekly_table = make_tier_table(weekly_subset, "DateOnly", last_7, "Date")
            if not weekly_table.empty:
                weekly_table["Date"] = weekly_table["Date"].apply(
                    lambda d: pd.to_datetime(str(d)).strftime("%B %-d, %Y") if d != "TOTAL" else d
                )
                all_cols = list(weekly_table.columns)
                col_config = {col: st.column_config.Column(width="small") for col in all_cols}
                def _style_weekly(col):
                    if col.name in highlight:
                        return ["background-color: #b0b0b0; color: black; font-weight: bold; text-align: center"] * len(col)
                    return ["text-align: center"] * len(col)
                styled = weekly_table.style.set_properties(**{"text-align": "center"}).apply(_style_weekly, axis=0).format({"Revenue": "${:,.2f}", "Monthly Sub Rev": "${:,.2f}", "Annual Sub Rev": "${:,.2f}"})
                st.dataframe(styled, use_container_width=True, hide_index=True, column_config=col_config)
            else:
                st.info("No new members in the last 7 days.")

        col_monthly, _ = st.columns([3, 1])
        with col_monthly:
            st.subheader("New Members by Month")
            patron_df["Month"] = patron_df["Date"].dt.to_period("M")
            months_this_year = [
                pd.Period(f"{this_year}-{m:02d}", freq="M")
                for m in range(1, this_month + 1)
            ]
            patron_df_year = patron_df[patron_df["Date"].dt.year == this_year]
            monthly_table = make_tier_table(patron_df_year, "Month", months_this_year, "Month")
            if not monthly_table.empty:
                monthly_table["Month"] = monthly_table["Month"].apply(
                    lambda p: pd.Period(str(p), freq="M").strftime("%B %Y") if p != "TOTAL" else p
                )
                all_cols = list(monthly_table.columns)
                col_config = {col: st.column_config.Column(width="small") for col in all_cols}
                def _style_monthly(col):
                    if col.name in highlight:
                        return ["background-color: #b0b0b0; color: black; font-weight: bold; text-align: center"] * len(col)
                    return ["text-align: center"] * len(col)
                styled = monthly_table.style.set_properties(**{"text-align": "center"}).apply(_style_monthly, axis=0).format({"Revenue": "${:,.2f}", "Monthly Sub Rev": "${:,.2f}", "Annual Sub Rev": "${:,.2f}"})
                st.dataframe(styled, use_container_width=True, hide_index=True, column_config=col_config)
            else:
                st.info("No member data for this year yet.")

        st.divider()

        st.subheader("New Patrons Over Time")
        by_month = patron_df.groupby(patron_df["Date"].dt.to_period("M")).size().reset_index()
        by_month.columns = ["Month", "New Patrons"]
        by_month["Month"] = by_month["Month"].astype(str)
        fig = px.bar(by_month, x="Month", y="New Patrons", title="New Patrons by Month", color_discrete_sequence=["#f96854"])
        st.plotly_chart(fig, use_container_width=True, key="patron_by_month")



# ============================
# TAB 3: YOUTUBE
# ============================

with tab3:
    st.subheader("YouTube Overview")
    col1, col2 = st.columns(2)
    col1.metric("Subscribers", f"{subscribers:,}")
    col2.metric("Total Views", f"{total_views:,}")

    if analytics_df is not None and not analytics_df.empty:
        st.divider()
        ytd_df = analytics_df[analytics_df["Date"].dt.year == this_year]
        st.subheader("Year-to-Date")
        col1, col2 = st.columns(2)
        with col1:
            fig = px.line(ytd_df, x="Date", y="Views", title="Daily Views (YTD)", color_discrete_sequence=["#f96854"])
            st.plotly_chart(fig, use_container_width=True, key="yt_views")
        with col2:
            fig = px.line(ytd_df, x="Date", y="Watch Time (mins)", title="Watch Time (YTD)", color_discrete_sequence=["#8ecae6"])
            st.plotly_chart(fig, use_container_width=True, key="yt_watchtime")
        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(ytd_df, x="Date", y="Subs Gained", title="Daily Subscribers Gained (YTD)", color_discrete_sequence=["#ffbe0b"])
            st.plotly_chart(fig, use_container_width=True, key="yt_subs_gained")
        with col2:
            weekly = ytd_df.resample("W", on="Date").sum().reset_index()
            fig = px.bar(weekly, x="Date", y="Net Subscribers", title="Weekly Net Subscribers (YTD)", color_discrete_sequence=["#f96854"])
            st.plotly_chart(fig, use_container_width=True, key="yt_weekly_subs")

        st.divider()
        st.subheader("Monthly Summary (YTD)")
        monthly = ytd_df.resample("ME", on="Date").sum().reset_index()
        monthly["Date"] = monthly["Date"].dt.strftime("%B %Y")
        st.dataframe(monthly[["Date", "Views", "Subs Gained", "Subs Lost", "Net Subscribers", "Watch Time (mins)"]], use_container_width=True, hide_index=True)

    if not videos_df.empty:
        st.divider()
        st.subheader("Top 10 Videos by Views")
        top10 = videos_df.head(10)
        fig = px.bar(top10, x="Views", y="Title", orientation="h", color="Views", color_continuous_scale="reds")
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="yt_top10")

        col1, col2 = st.columns(2)
        with col1:
            fig = px.scatter(videos_df.head(20), x="Views", y="Likes", hover_name="Title", size="Comments", color="Views", color_continuous_scale="reds", title="Views vs Likes")
            st.plotly_chart(fig, use_container_width=True, key="yt_scatter")
        with col2:
            videos_df["Published"] = pd.to_datetime(videos_df["Published"])
            by_month = videos_df.groupby(videos_df["Published"].dt.to_period("M")).size().reset_index()
            by_month.columns = ["Month", "Videos"]
            by_month["Month"] = by_month["Month"].astype(str)
            fig = px.bar(by_month, x="Month", y="Videos", title="Upload Frequency by Month", color_discrete_sequence=["#f96854"])
            st.plotly_chart(fig, use_container_width=True, key="yt_upload_freq")

        st.divider()
        st.subheader("All Videos")
        st.dataframe(videos_df[["Title", "Published", "Views", "Likes", "Comments"]], use_container_width=True, hide_index=True)
