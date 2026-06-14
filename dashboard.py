import streamlit as st
import requests
import os
import tempfile
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
 
load_dotenv()
 
st.set_page_config(page_title="Dashboard", page_icon="🎬", layout="wide")
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
 
active = [m for m in members if m["attributes"].get("patron_status") == "active_patron"]
declined = [m for m in members if m["attributes"].get("patron_status") == "declined_patron"]
former = [m for m in members if m["attributes"].get("patron_status") == "former_patron"]
followers = [m for m in members if m["attributes"].get("is_follower")]
 
def monthly_amount(m):
    amount = m["attributes"].get("currently_entitled_amount_cents", 0)
    cadence = m["attributes"].get("pledge_cadence", 1)
    if cadence == 12:
        return amount / 12 / 100
    return amount / 100
 
monthly_revenue = sum(monthly_amount(m) for m in active)
lifetime_revenue = sum(m["attributes"].get("campaign_lifetime_support_cents", 0) for m in members) / 100
next_month_rev = sum(m["attributes"].get("will_pay_amount_cents", 0) for m in active) / 100
 
today = datetime.today()
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
            "Status": m["attributes"].get("patron_status")
        })
patron_df = pd.DataFrame(patron_records) if patron_records else pd.DataFrame()
 
def signups_for(year, month):
    if patron_df.empty:
        return 0
    return len(patron_df[(patron_df["Date"].dt.year == year) & (patron_df["Date"].dt.month == month)])
 
signups_this_month = signups_for(this_year, this_month)
signups_last_month = signups_for(last_month_year, last_month)
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
 
def make_tier_table(df, period_col, period_values, period_label):
    if df.empty:
        return pd.DataFrame()
    tiers = sorted(df["Tier"].unique())
    rows = []
    for period in period_values:
        row = {period_label: str(period)}
        period_data = df[df[period_col] == period]
        for tier in tiers:
            row[tier] = len(period_data[period_data["Tier"] == tier])
        row["Total Members"] = len(period_data)
        row["Total Revenue ($)"] = round(period_data["Amount"].sum(), 2)
        rows.append(row)
    total_row = {period_label: "TOTAL"}
    for tier in tiers:
        total_row[tier] = len(df[df["Tier"] == tier])
    total_row["Total Members"] = len(df)
    total_row["Total Revenue ($)"] = round(df["Amount"].sum(), 2)
    rows.append(total_row)
    return pd.DataFrame(rows)
 
# ============================
# TAB 1: DASHBOARD
# ============================
 
with tab1:
    st.subheader("Dashboard")
 
    st.markdown("**AdSense Revenue**")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month", f"${adsense_this:.2f}", delta=f"${adsense_delta:+.2f} vs last month", delta_color="normal")
    col2.metric("Last Month", f"${adsense_last:.2f}")
    col3.metric("12-Month Avg", f"${adsense_avg:.2f}")
 
    st.divider()
 
    st.markdown("**Patreon Revenue**")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month", f"${patreon_this_month:.2f}", delta=f"${patreon_delta:+.2f} vs last month", delta_color="normal")
    col2.metric("Last Month", f"${patreon_last_month:.2f}")
    col3.metric("Current MRR", f"${monthly_revenue:.2f}")
 
    st.divider()
 
    st.markdown("**YouTube Views**")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month", f"{yt_views_this:,}", delta=f"{yt_views_this - yt_views_last:+,} vs last month", delta_color="normal")
    col2.metric("Last Month", f"{yt_views_last:,}")
    col3.metric("12-Month Avg", f"{yt_views_avg:,}")
 
    st.divider()
 
    st.markdown("**YouTube Subscribers**")
    col1, col2, col3 = st.columns(3)
    col1.metric("This Month (Net)", f"{yt_subs_this:+,}", delta=f"{yt_subs_this - yt_subs_last:+,} vs last month", delta_color="normal")
    col2.metric("Last Month (Net)", f"{yt_subs_last:+,}")
    col3.metric("12-Month Avg (Net)", f"{yt_subs_avg:+,}")
 
    if analytics_df is not None and not analytics_df.empty:
        st.divider()
        st.subheader("Year-to-Date")
        ytd_df = analytics_df[analytics_df["Date"].dt.year == this_year]
        col1, col2 = st.columns(2)
        with col1:
            fig = px.line(ytd_df, x="Date", y="Views", title="Daily Views (YTD)", color_discrete_sequence=["#f96854"])
            st.plotly_chart(fig, use_container_width=True, key="overview_views")
        with col2:
            fig = px.bar(ytd_df, x="Date", y="Net Subscribers", title="Daily Net Subscribers (YTD)", color_discrete_sequence=["#ffbe0b"])
            st.plotly_chart(fig, use_container_width=True, key="overview_subs")
 
# ============================
# TAB 2: PATREON
# ============================
 
with tab2:
    st.subheader("Patreon Overview")
 
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Signups This Month", signups_this_month, delta=f"{signups_delta:+} vs last month", delta_color="normal")
    col2.metric("Signups Last Month", signups_last_month)
    col3.metric("Cancellations This Month", cancel_this_month, delta=f"{cancel_delta:+} vs last month", delta_color="inverse")
    col4.metric("Cancellations Last Month", cancel_last_month)
 
    st.divider()
 
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active Members", len(active))
    col2.metric("Monthly Revenue", f"${monthly_revenue:.2f}")
    col3.metric("Lifetime Revenue", f"${lifetime_revenue:.2f}")
    col4.metric("Projected Next Month", f"${next_month_rev:.2f}")
 
    col1, col2, col3 = st.columns(3)
    col1.metric("Declined Members", len(declined))
    col2.metric("Former Members", len(former))
    col3.metric("Followers (non-paying)", len(followers))
 
    st.divider()
 
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Member Status Breakdown")
        fig = px.pie(
            values=[len(active), len(declined), len(former)],
            names=["Active", "Declined", "Former"],
            color_discrete_sequence=["#f96854", "#ffbe0b", "#8ecae6"]
        )
        st.plotly_chart(fig, use_container_width=True, key="patron_pie")
    with col2:
        st.subheader("Revenue Summary")
        fig = px.bar(
            x=["Monthly Revenue", "Projected Next Month", "Lifetime Revenue"],
            y=[monthly_revenue, next_month_rev, lifetime_revenue],
            color_discrete_sequence=["#f96854"],
            labels={"x": "", "y": "USD ($)"}
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="patron_revenue_bar")
 
    if not patron_df.empty:
        st.divider()
 
        st.subheader("New Members This Week")
        last_7 = [today.date() - timedelta(days=i) for i in range(6, -1, -1)]
        patron_df["DateOnly"] = patron_df["Date"].dt.date
        weekly_subset = patron_df[patron_df["DateOnly"].isin(last_7)]
        weekly_table = make_tier_table(weekly_subset, "DateOnly", last_7, "Date")
        if not weekly_table.empty:
            weekly_table["Date"] = weekly_table["Date"].apply(
                lambda d: pd.to_datetime(str(d)).strftime("%-d %B %Y") if d != "TOTAL" else d
            )
            all_cols = list(weekly_table.columns)
            col_config = {col: st.column_config.Column(width="medium") for col in all_cols}
            st.dataframe(
                weekly_table.style.set_properties(**{"text-align": "center"}),
                use_container_width=True,
                hide_index=True,
                column_config=col_config
            )
        else:
            st.info("No new members in the last 7 days.")
 
        st.divider()
 
        st.subheader("New Members by Month (This Year)")
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
            col_config = {col: st.column_config.Column(width="medium") for col in all_cols}
            st.dataframe(
                monthly_table.style.set_properties(**{"text-align": "center"}),
                use_container_width=True,
                hide_index=True,
                column_config=col_config
            )
        else:
            st.info("No member data for this year yet.")
 
        st.divider()
 
        st.subheader("New Patrons Over Time")
        col1, col2 = st.columns(2)
        with col1:
            by_month = patron_df.groupby(patron_df["Date"].dt.to_period("M")).size().reset_index()
            by_month.columns = ["Month", "New Patrons"]
            by_month["Month"] = by_month["Month"].astype(str)
            fig = px.bar(by_month, x="Month", y="New Patrons", title="New Patrons by Month", color_discrete_sequence=["#f96854"])
            st.plotly_chart(fig, use_container_width=True, key="patron_by_month")
        with col2:
            by_week = patron_df.groupby(patron_df["Date"].dt.to_period("W")).size().reset_index()
            by_week.columns = ["Week", "New Patrons"]
            by_week["Week"] = by_week["Week"].astype(str)
            fig = px.bar(by_week, x="Week", y="New Patrons", title="New Patrons by Week", color_discrete_sequence=["#ffbe0b"])
            st.plotly_chart(fig, use_container_width=True, key="patron_by_week")
 
    st.divider()
    export_df = pd.DataFrame([{
        "Name": m["attributes"].get("full_name"),
        "Tier": m.get("tier", "No Tier"),
        "Status": m["attributes"].get("patron_status"),
        "Monthly ($)": monthly_amount(m),
        "Lifetime ($)": m["attributes"].get("campaign_lifetime_support_cents", 0) / 100,
        "Last Charge": m["attributes"].get("last_charge_date", "")[:10] if m["attributes"].get("last_charge_date") else "",
        "Member Since": m["attributes"].get("pledge_relationship_start", "")[:10] if m["attributes"].get("pledge_relationship_start") else "",
    } for m in members])
    st.download_button("⬇️ Export Patreon Data to CSV", export_df.to_csv(index=False), "patreon_members.csv", "text/csv")
 
    # ============================
    # HISTORICAL EARNINGS UPLOAD
    # ============================
 
    st.divider()
    st.subheader("📂 Historical Earnings (Patreon Export)")
    st.caption("Upload your Patreon earnings file: Patreon dashboard → Finance → Payouts → Export. Accepts .xlsx or .csv.")
 
    uploaded_file = st.file_uploader("Upload Patreon export file", type=["xlsx", "xls", "csv"], label_visibility="collapsed")
 
    def find_col(df, candidates):
        """Return the first matching column name from a list of candidates (case-insensitive)."""
        lower_map = {c.lower().strip(): c for c in df.columns}
        for cand in candidates:
            if cand.lower() in lower_map:
                return lower_map[cand.lower()]
        return None
 
    if uploaded_file is not None:
        try:
            ext = uploaded_file.name.split(".")[-1].lower()
 
            if ext in ("xlsx", "xls"):
                xl = pd.ExcelFile(uploaded_file)
                sheet_names = [s.lower() for s in xl.sheet_names]
                raw_names = xl.sheet_names
 
                def get_sheet(keywords):
                    for kw in keywords:
                        for i, s in enumerate(sheet_names):
                            if kw in s:
                                return pd.read_excel(xl, sheet_name=raw_names[i])
                    return None
 
                payouts_df   = get_sheet(["payout"])
                earnings_df  = get_sheet(["earning", "payment", "charge"])
                members_hist = get_sheet(["member"])
            else:
                # Single CSV — try to figure out which sheet it is
                single = pd.read_csv(uploaded_file)
                payouts_df = earnings_df = members_hist = None
                cols_lower = [c.lower() for c in single.columns]
                if any("payout" in c or "net" in c for c in cols_lower):
                    payouts_df = single
                elif any("patron" in c or "charge" in c or "earning" in c for c in cols_lower):
                    earnings_df = single
                else:
                    members_hist = single
 
            # ---- PAYOUTS SHEET ----
            if payouts_df is not None and not payouts_df.empty:
                st.markdown("### Payouts")
                date_col   = find_col(payouts_df, ["date", "month", "payout date", "period"])
                gross_col  = find_col(payouts_df, ["gross", "gross earnings", "total earnings", "total"])
                net_col    = find_col(payouts_df, ["net", "net payout", "you receive", "amount paid"])
                fees_col   = find_col(payouts_df, ["fees", "fee", "processing fees", "platform fee"])
 
                if date_col:
                    payouts_df[date_col] = pd.to_datetime(payouts_df[date_col], errors="coerce")
                    payouts_df = payouts_df.dropna(subset=[date_col]).sort_values(date_col)
                    payouts_df["Month Label"] = payouts_df[date_col].dt.strftime("%B %Y")
 
                    if gross_col or net_col:
                        col1, col2 = st.columns(2)
                        if gross_col:
                            payouts_df[gross_col] = pd.to_numeric(payouts_df[gross_col], errors="coerce")
                            total_gross = payouts_df[gross_col].sum()
                            col1.metric("Total Gross Earnings", f"${total_gross:,.2f}")
                            fig = px.bar(payouts_df, x="Month Label", y=gross_col,
                                         title="Gross Earnings by Month",
                                         color_discrete_sequence=["#f96854"],
                                         labels={gross_col: "Gross ($)", "Month Label": ""})
                            st.plotly_chart(fig, use_container_width=True, key="payout_gross")
                        if net_col:
                            payouts_df[net_col] = pd.to_numeric(payouts_df[net_col], errors="coerce")
                            total_net = payouts_df[net_col].sum()
                            col2.metric("Total Net Payouts", f"${total_net:,.2f}")
                            fig = px.bar(payouts_df, x="Month Label", y=net_col,
                                         title="Net Payout by Month",
                                         color_discrete_sequence=["#ffbe0b"],
                                         labels={net_col: "Net ($)", "Month Label": ""})
                            st.plotly_chart(fig, use_container_width=True, key="payout_net")
 
                    # Cumulative earnings
                    if gross_col:
                        payouts_df["Cumulative"] = payouts_df[gross_col].cumsum()
                        fig = px.line(payouts_df, x="Month Label", y="Cumulative",
                                      title="Cumulative Gross Earnings",
                                      color_discrete_sequence=["#8ecae6"],
                                      labels={"Cumulative": "Total ($)", "Month Label": ""})
                        st.plotly_chart(fig, use_container_width=True, key="payout_cumulative")
 
                    st.dataframe(payouts_df.drop(columns=["Month Label"], errors="ignore"),
                                 use_container_width=True, hide_index=True)
                else:
                    st.warning("Couldn't detect a date column in the Payouts sheet.")
 
            # ---- EARNINGS SHEET ----
            if earnings_df is not None and not earnings_df.empty:
                st.markdown("### Earnings by Patron")
                date_col   = find_col(earnings_df, ["charge date", "date", "payment date", "created"])
                amount_col = find_col(earnings_df, ["amount", "charge amount", "amount (usd)", "total"])
                status_col = find_col(earnings_df, ["status", "payment status", "charge status"])
                tier_col   = find_col(earnings_df, ["tier", "tier name", "membership level", "level"])
                name_col   = find_col(earnings_df, ["patron name", "name", "patron"])
 
                if amount_col:
                    earnings_df[amount_col] = pd.to_numeric(earnings_df[amount_col], errors="coerce")
 
                if date_col:
                    earnings_df[date_col] = pd.to_datetime(earnings_df[date_col], errors="coerce")
                    earnings_df = earnings_df.dropna(subset=[date_col])
 
                    # Filter to paid only if status column exists
                    paid_df = earnings_df
                    if status_col:
                        paid_df = earnings_df[earnings_df[status_col].astype(str).str.lower().isin(["paid", "successful", "success", "completed"])]
 
                    if amount_col and not paid_df.empty:
                        paid_df = paid_df.copy()
                        paid_df["Month"] = paid_df[date_col].dt.to_period("M")
                        paid_df["Month Label"] = paid_df[date_col].dt.strftime("%B %Y")
 
                        monthly_earnings = paid_df.groupby("Month Label")[amount_col].sum().reset_index()
                        monthly_earnings.columns = ["Month", "Earned ($)"]
 
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Total Earned (all time)", f"${paid_df[amount_col].sum():,.2f}")
                        col2.metric("Avg per Month", f"${paid_df[amount_col].sum() / max(paid_df['Month'].nunique(), 1):,.2f}")
                        col3.metric("Transactions", f"{len(paid_df):,}")
 
                        fig = px.bar(monthly_earnings, x="Month", y="Earned ($)",
                                     title="Monthly Earnings (Paid Charges)",
                                     color_discrete_sequence=["#f96854"],
                                     labels={"Month": ""})
                        st.plotly_chart(fig, use_container_width=True, key="earnings_monthly")
 
                        # By tier if available
                        if tier_col:
                            tier_monthly = paid_df.groupby(["Month Label", tier_col])[amount_col].sum().reset_index()
                            tier_monthly.columns = ["Month", "Tier", "Earned ($)"]
                            fig = px.bar(tier_monthly, x="Month", y="Earned ($)", color="Tier",
                                         title="Monthly Earnings by Tier",
                                         labels={"Month": ""},
                                         color_discrete_sequence=px.colors.qualitative.Set2)
                            st.plotly_chart(fig, use_container_width=True, key="earnings_by_tier")
 
                else:
                    st.warning("Couldn't detect a date column in the Earnings sheet.")
 
            # ---- MEMBERS SHEET ----
            if members_hist is not None and not members_hist.empty:
                st.markdown("### Member History")
                start_col  = find_col(members_hist, ["pledge start", "member since", "start date", "joined", "created"])
                status_col = find_col(members_hist, ["status", "patron status"])
                tier_col   = find_col(members_hist, ["tier", "tier name", "membership level", "level"])
                amount_col = find_col(members_hist, ["amount", "pledge amount", "monthly amount"])
 
                if start_col:
                    members_hist[start_col] = pd.to_datetime(members_hist[start_col], errors="coerce")
                    members_hist = members_hist.dropna(subset=[start_col])
                    members_hist["Month"] = members_hist[start_col].dt.strftime("%B %Y")
                    members_hist["Year"] = members_hist[start_col].dt.year
 
                    signups_by_month = members_hist.groupby("Month").size().reset_index(name="New Members")
                    fig = px.bar(signups_by_month, x="Month", y="New Members",
                                 title="New Members by Month (All Time)",
                                 color_discrete_sequence=["#f96854"],
                                 labels={"Month": ""})
                    st.plotly_chart(fig, use_container_width=True, key="hist_signups")
 
                    if tier_col:
                        tier_dist = members_hist[tier_col].value_counts().reset_index()
                        tier_dist.columns = ["Tier", "Members"]
                        fig = px.pie(tier_dist, names="Tier", values="Members",
                                     title="Members by Tier",
                                     color_discrete_sequence=px.colors.qualitative.Set2)
                        st.plotly_chart(fig, use_container_width=True, key="hist_tier_pie")
 
                col1, col2 = st.columns(2)
                col1.metric("Total Members in Export", f"{len(members_hist):,}")
                if status_col:
                    active_count = len(members_hist[members_hist[status_col].astype(str).str.lower().str.contains("active")])
                    col2.metric("Active in Export", f"{active_count:,}")
 
                st.dataframe(members_hist, use_container_width=True, hide_index=True)
 
            if payouts_df is None and earnings_df is None and members_hist is None:
                st.warning("Couldn't identify any sheets. Make sure the file is the Patreon earnings export.")
 
        except Exception as e:
            st.error(f"Error reading file: {e}")
 
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
 