import os
import re
import urllib.parse
import sqlite3
import datetime
import pandas as pd
import streamlit as st

# ==================== 0. 权限与账号配置 ====================
USER_CREDENTIALS = {
    "admin": "admin888",
    "zhang": "jp666",
    "huang": "jp666",
    "buyer03": "jp999"
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "aba_company_shared_v2.db")

# 中国卖家禁限售黑名单类目与词库 (自动拦截)
CHINA_SELLER_BANNED_WORDS = [
    # 医疗与医疗器械
    "医療", "医療機器", "コンタクト", "カラコン", "パルスオキシメーター", "血圧計", "体温計", 
    "補聴器", "血糖", "注射", "インスリン", "ギプス", "包帯", "点滴", "鍼", "針灸",
    # 药品 (处方药、OTC、外用药膏)
    "医薬品", "第1類", "第2類", "第3類", "指定第2類", "処方", "目薬", "点眼", "風邪薬", 
    "ロキソニン", "イブ", "パブロン", "アレグラ", "ステロイド", "軟膏", "胃腸薬", "漢方", 
    "解熱", "鎮痛", "湿布", "シップ", "抗生", "点鼻",
    # 保健品与营养补充剂
    "サプリ", "サプリメント", "プロテイン", "ビタミン", "亜鉛", "乳酸菌", "青汁", 
    "コラーゲン", "酵素", "ダイエット食品", "健康食品", "DHA", "EPA", "マカ", "CBD", "グミサプリ",
    # 食品、生鲜、烟酒与饮料
    "食品", "お菓子", "スイーツ", "チョコレート", "米", "肉", "魚", "ビール", "ウイスキー", 
    "ワイン", "お酒", "焼酎", "タバコ", "電子タバコ", "リキッド", "シーシャ", "コーヒー", "お茶",
    # 影视、实体唱片、音乐周边
    "映画", "ドラマ", "Blu-ray", "ブルーレイ", "DVD", "CD", "アルバム", "ミュージック", 
    "サントラ", "サウンドトラック", "主題歌", "劇場版", "全巻", "BOX", "初回限定", "コンサート", "ライブ", "OST",
    # 版权图书、漫画、卡牌与IP周边
    "コミック", "漫画", "単行本", "小説", "雑誌", "写真集", "カレンダー", "トレカ", 
    "ポケモンカード", "ポケカ", "ワンピースカード", "一番くじ", "集英社", "KADOKAWA", "講談社", "小学館", "SQUARE ENIX"
]
BANNED_REGEX_PATTERN = '|'.join([re.escape(w) for w in CHINA_SELLER_BANNED_WORDS])

# ==================== 1. SQLite 极速数据库引擎 ====================
def get_db_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA cache_size = -64000;")
    return conn

def init_database():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aba_data (
            file_date TEXT, keyword TEXT, sfr_rank INTEGER,
            asin1 TEXT, c1 REAL, v1 REAL, 
            asin2 TEXT, c2 REAL, v2 REAL, 
            asin3 TEXT, c3 REAL, v3 REAL,
            PRIMARY KEY (file_date, keyword)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date_kw ON aba_data(file_date, keyword);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date_rank ON aba_data(file_date, sfr_rank);")
    cursor.execute("CREATE TABLE IF NOT EXISTS aba_favorites (keyword TEXT PRIMARY KEY, add_date TEXT);")
    cursor.execute("CREATE TABLE IF NOT EXISTS aba_clicks (keyword TEXT PRIMARY KEY, click_time TIMESTAMP);")
    conn.commit()
    conn.close()

def save_to_database(df, file_date):
    if df is None or df.empty:
        return 0, 0
    conn = get_db_conn()
    cursor = conn.cursor()
    total_raw = len(df)
    try:
        df_clean = pd.DataFrame()
        df_clean['keyword'] = df.iloc.astype(str).str.strip()
        df_clean['sfr_rank'] = pd.to_numeric(df.iloc[:, 0].astype(str).str.replace(',', ''), errors='coerce')
        
        # 剔除数字/虚拟类目
        ultimate_blacklist = ["Digital", "Video", "Book", "Music", "Ebook", "Magazine", "Audible", "Fresh", "Grocery", "Perishable", "Prime Video"]
        category_cols = [c for c in (5, 6, 7) if c in df.columns]
        if category_cols:
            cat_mask = pd.Series(False, index=df.index)
            for c in category_cols:
                cat_mask |= df[c].astype(str).str.contains('|'.join(ultimate_blacklist), case=False, na=False)
            df_clean = df_clean[~cat_mask]
                
        # 剔除中国卖家禁做词
        banned_mask = df_clean['keyword'].str.contains(BANNED_REGEX_PATTERN, case=False, na=False)
        df_clean = df_clean[~banned_mask]

        def clean_pct(series):
            return pd.to_numeric(series.astype(str).str.rstrip('%'), errors='coerce').fillna(0)
            
        df_clean['asin1'] = df.iloc[:, 8].astype(str).str.strip() if 8 < df.shape else ""
        df_clean['c1'] = clean_pct(df.iloc[:, 10]) if 10 < df.shape else 0
        df_clean['v1'] = clean_pct(df.iloc[:, 11]) if 11 < df.shape else 0
        
        df_clean['asin2'] = df.iloc[:, 12].astype(str).str.strip() if 12 < df.shape else ""
        df_clean['c2'] = clean_pct(df.iloc[:, 14]) if 14 < df.shape else 0
        df_clean['v2'] = clean_pct(df.iloc[:, 15]) if 15 < df.shape else 0
        
        df_clean['asin3'] = df.iloc[:, 16].astype(str).str.strip() if 16 < df.shape else ""
        df_clean['c3'] = clean_pct(df.iloc[:, 18]) if 18 < df.shape else 0
        df_clean['v3'] = clean_pct(df.iloc[:, 19]) if 19 < df.shape else 0
        df_clean['file_date'] = file_date
        
        df_clean = df_clean.dropna(subset=['keyword', 'sfr_rank'])
        
        insert_query = """INSERT OR REPLACE INTO aba_data 
                          (file_date, keyword, sfr_rank, asin1, c1, v1, asin2, c2, v2, asin3, c3, v3) 
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        data_to_insert = df_clean[['file_date', 'keyword', 'sfr_rank', 'asin1', 'c1', 'v1', 'asin2', 'c2', 'v2', 'asin3', 'c3', 'v3']].values.tolist()
        cursor.executemany(insert_query, data_to_insert)
        conn.commit()
        success_count = len(df_clean)
    except Exception as e:
        st.sidebar.error(f"写入异常: {e}")
        success_count = 0
    finally:
        conn.close()
    return success_count, (total_raw - success_count)

def get_available_dates():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT file_date FROM aba_data ORDER BY file_date ASC")
    dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    return dates

def get_daily_surge_analysis(latest_date, prev_date, max_sfr=100000):
    conn = get_db_conn()
    query = """
        SELECT 
            t.keyword,
            t.sfr_rank AS sfr_curr,
            p.sfr_rank AS sfr_prev,
            (CASE WHEN p.sfr_rank IS NULL THEN 999999 ELSE (p.sfr_rank - t.sfr_rank) END) AS rank_jump,
            (CASE WHEN p.sfr_rank IS NULL THEN 999.0 ELSE ROUND((p.sfr_rank - t.sfr_rank) * 100.0 / p.sfr_rank, 1) END) AS growth_pct,
            t.asin1, t.c1, t.v1,
            t.asin2, t.c2, t.v2,
            t.asin3, t.c3, t.v3,
            (t.c1 + t.c2 + t.c3) AS click_total,
            (t.v1 + t.v2 + t.v3) AS trans_total,
            (t.v1 / (t.c1 + 0.0001)) AS top1_power
        FROM aba_data t
        LEFT JOIN aba_data p ON t.keyword = p.keyword AND p.file_date = ?
        WHERE t.file_date = ? AND t.sfr_rank <= ?
    """
    df = pd.read_sql_query(query, conn, params=(prev_date, latest_date, max_sfr))
    conn.close()
    return df

def record_keyword_click(kw):
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("INSERT OR REPLACE INTO aba_clicks VALUES (?, ?)", (kw.strip(), now_str))
        conn.commit()
    finally:
        conn.close()

def get_recent_clicks():
    conn = get_db_conn()
    cursor = conn.cursor()
    one_day_ago = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("DELETE FROM aba_clicks WHERE click_time < ?", (one_day_ago,))
    conn.commit()
    cursor.execute("SELECT keyword FROM aba_clicks")
    clicked_kws = [row[0] for row in cursor.fetchall()]
    conn.close()
    return clicked_kws

def add_to_favorites(kw):
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO aba_favorites VALUES (?, date('now'))", (kw.strip(),))
        conn.commit()
    finally:
        conn.close()

def remove_from_favorites(kw):
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM aba_favorites WHERE keyword = ?", (kw.strip(),))
        conn.commit()
    finally:
        conn.close()

def get_all_favorites():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT keyword FROM aba_favorites ORDER BY add_date DESC")
    kws = [row[0] for row in cursor.fetchall()]
    conn.close()
    return kws

# ==================== 2. 高级 UI 样式注入 ====================
init_database()
st.set_page_config(page_title="日亚选品与暴涨雷达 Pro", layout="wide", initial_sidebar_state="expanded")

if 'temp_deleted_keywords' not in st.session_state:
    st.session_state['temp_deleted_keywords'] = set()

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif !important; }
    .stApp { background-color: #F8FAFC !important; color: #1E293B !important; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    section[data-testid="stSidebar"] { background-color: #FFFFFF !important; border-right: 1px solid #E2E8F0 !important; }
    .metric-card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .metric-label { font-size: 13px; color: #64748B; font-weight: 600; display: flex; justify-content: space-between; }
    .metric-value { font-size: 26px; font-weight: 700; color: #0F172A; margin: 6px 0; }
    .metric-sub { font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 6px; }
    .badge-blue { background-color: #EFF6FF; color: #2563EB; }
    .badge-red { background-color: #FEF2F2; color: #DC2626; }
    .badge-green { background-color: #ECFDF5; color: #059669; }
    .badge-amber { background-color: #FFFBEB; color: #D97706; }
    div[data-testid="stTabs"] button { font-weight: 600 !important; font-size: 14px !important; color: #64748B !important; }
    div[data-testid="stTabs"] button[aria-selected="true"] { background-color: #FFFFFF !important; color: #2563EB !important; }
    div[data-testid="stDataEditor"] { background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 12px !important; }
    a { color: #2563EB !important; text-decoration: none !important; font-weight: 600; }
    a:hover { text-decoration: underline !important; }
    </style>
""", unsafe_allow_html=True)

# ==================== 3. 登录认证控制 ====================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""

if not st.session_state['logged_in']:
    st.markdown("""
        <div style='text-align: center; margin-top: 100px; margin-bottom: 25px;'>
            <div style='display:inline-block; padding: 10px 14px; background:#EFF6FF; border-radius:12px; margin-bottom:12px;'>
                <span style='font-size:24px;'>🚀</span>
            </div>
            <h2 style='color: #0F172A; font-weight: 700; margin:0;'>日亚选品与关键词暴涨雷达 Pro</h2>
            <p style='color: #64748B; font-size: 14px; margin-top: 6px;'>智能屏蔽非实物与违禁类目 · 毫秒级洞察每日黑马品</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, login_card, col3 = st.columns(3)
    with login_card:
        with st.form("SaaS安全认证"):
            u = st.text_input("👤 运营专员账号")
            p = st.text_input("🔒 登录密码", type="password")
            if st.form_submit_button("进入选品雷达", use_container_width=True, type="primary"):
                if u in USER_CREDENTIALS and USER_CREDENTIALS[u] == p:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = u
                    st.rerun()
                else:
                    st.error("❌ 凭证失效，请检查账号密码")
    st.stop()

# ==================== 4. 侧边栏：极简导入中心 ====================
st.sidebar.markdown(f"""
    <div style='display:flex; align-items:center; gap:8px; padding-bottom:12px;'>
        <div style='width:32px; height:32px; border-radius:8px; background:#2563EB; color:white; display:flex; align-items:center; justify-content:center; font-weight:700;'>
            {st.session_state['username'][0].upper()}
        </div>
        <div>
            <div style='font-weight:700; font-size:14px; color:#0F172A;'>{st.session_state['username']}</div>
            <div style='font-size:11px; color:#10B981; font-weight:600;'>● 监控在线</div>
        </div>
    </div>
""", unsafe_allow_html=True)

if st.sidebar.button("安全登出", use_container_width=True):
    st.session_state['logged_in'] = False
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📥 导入每日 ABA 报告")
uploaded_files = st.sidebar.file_uploader("拖入亚马逊官方 CSV 报表：", type=["csv"], accept_multiple_files=True)
if uploaded_files:
    for f in uploaded_files:
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", f.name)
        if date_match:
            target_date = date_match.group(0)
            with st.spinner(f"正在闪电过滤并入库 {target_date}..."):
                try:
                    raw_df = pd.read_csv(f, skiprows=2, header=None, low_memory=False, dtype=str, encoding='utf-8', encoding_errors='ignore')
                except:
                    raw_df = pd.read_csv(f, skiprows=2, header=None, low_memory=False, dtype=str, encoding='shift_jis', encoding_errors='ignore')
                suc, err = save_to_database(raw_df, target_date)
            st.sidebar.success(f"✅ {target_date}：净入库 {suc:,} 条")

db_dates = get_available_dates()

st.sidebar.markdown("---")
st.sidebar.markdown("##### 🛡️ 合规过滤设置")
enable_banned_filter = st.sidebar.checkbox("彻底剔除医疗/药品/保健品/影视", value=True)

st.sidebar.markdown("##### 🚨 预警触发门槛")
radar_sfr_limit = st.sidebar.number_input("排名观察上限 (SFR)", value=80000, step=10000)
min_jump_places = st.sidebar.number_input("名次暴涨跨度门槛 (位)", value=10000, step=5000)
min_growth_pct = st.sidebar.slider("最小飙升百分比 (%)", 10, 90, 35, 5)

custom_exclude = st.sidebar.text_input("补充排除词（逗号隔开）")

# ==================== 5. 主看板：全新极简舒适工作台 ====================
if len(db_dates) >= 2:
    latest_date = db_dates[-1]
    prev_date = db_dates[-2]
    
    st.markdown(f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:12px; padding:14px 20px; display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <span style="font-size:20px;">📡</span>
                <div>
                    <span style="font-weight:700; color:#0F172A; font-size:15px;">暴涨雷达处于实时就绪状态</span>
                    <span style="color:#64748B; font-size:13px; margin-left:8px;">自动比对：<b style="color:#1E293B;">{prev_date}</b> ➔ <b style="color:#2563EB;">{latest_date} (最新)</b></span>
                </div>
            </div>
            <div style="font-size:12px; background:#ECFDF5; color:#059669; padding:4px 10px; border-radius:20px; font-weight:600;">
                已开启中国卖家实物合规保护
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    surge_df = get_daily_surge_analysis(latest_date, prev_date, max_sfr=radar_sfr_limit)
    
    if not surge_df.empty:
        if enable_banned_filter:
            surge_df = surge_df[~surge_df['keyword'].str.contains(BANNED_REGEX_PATTERN, case=False, na=False)]
        if custom_exclude:
            for ew in [w.strip() for w in custom_exclude.split(",") if w.strip()]:
                surge_df = surge_df[~surge_df['keyword'].str.contains(ew, case=False, na=False)]
        if st.session_state['temp_deleted_keywords']:
            surge_df = surge_df[~surge_df['keyword'].isin(st.session_state['temp_deleted_keywords'])]
            
        clicked_kws = get_recent_clicks()
        fav_list = get_all_favorites()
        
        new_stars = surge_df[surge_df['sfr_prev'].isna()].sort_values(by='sfr_curr', ascending=True)
        jumpers = surge_df[
            (surge_df['rank_jump'] >= min_jump_places) | 
            (surge_df['growth_pct'] >= min_growth_pct)
        ].sort_values(by='rank_jump', ascending=False)
        paper_tigers = surge_df[
            ((surge_df['rank_jump'] >= 5000) | (surge_df['sfr_prev'].isna())) &
            (surge_df['top1_power'] < 0.85) &
            (surge_df['c1'] > 20)
        ].sort_values(by='sfr_curr', ascending=True)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">今日纯净实物词 <span>📦</span></div>
                    <div class="metric-value">{len(surge_df):,}</div>
                    <span class="metric-sub badge-blue">≤ {radar_sfr_limit:,} 榜单内</span>
                </div>
            """, unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">空降新星词 <span>⚡</span></div>
                    <div class="metric-value">{len(new_stars)}</div>
                    <span class="metric-sub badge-red">全网突发全新需求</span>
                </div>
            """, unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">排名暴涨热词 <span>🚀</span></div>
                    <div class="metric-value">{len(jumpers)}</div>
                    <span class="metric-sub badge-green">净升超 {min_jump_places:,} 名</span>
                </div>
            """, unsafe_allow_html=True)
        with c4:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">暴涨纸老虎 (商机) <span>🐯</span></div>
                    <div class="metric-value">{len(paper_tigers)}</div>
                    <span class="metric-sub badge-amber">头部转化差 · 易突破</span>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

        search_col, sort_col = st.columns(2)
        with search_col:
            inpage_search = st.text_input("即时搜索关键词 / ASIN：", label_visibility="collapsed", placeholder="🔍 快速搜索关键词 / ASIN（即输即显）...")
        with sort_col:
            sort_option = st.selectbox("排序方式", ["按名次提升幅度 (从高到低)", "按今日最新排名 (从前到后)", "按第1名点击占比"], label_visibility="collapsed")

        def apply_quick_filter(df_in):
            d = df_in.copy()
            if inpage_search:
                d = d[d['keyword'].str.contains(inpage_search.strip(), case=False, na=False) | d['asin1'].str.contains(inpage_search.strip(), case=False, na=False)]
            if sort_option == "按名次提升幅度 (从高到低)":
                d = d.sort_values(by='rank_jump', ascending=False)
            elif sort_option == "按今日最新排名 (从前到后)":
                d = d.sort_values(by='sfr_curr', ascending=True)
            elif sort_option == "按第1名点击占比":
                d = d.sort_values(by='c1', ascending=False)
            return d

        tab_new, tab_jump, tab_tiger, tab_fav, tab_all = st.tabs([
            f"⚡ 空降新星 ({len(new_stars)})", 
            f"🚀 排名暴涨 ({len(jumpers)})", 
            f"🐯 暴涨纸老虎 ({len(paper_tigers)})",
            f"⭐ 重点监控 ({len(fav_list)})",
            f"📋 全量数据池 ({len(surge_df)})"
        ])
        
        def render_clean_table(df_raw, tab_key):
            df_filtered = apply_quick_filter(df_raw)
            if df_filtered.empty:
                st.info("💡 当前筛选或搜索条件下无匹配关键词。")
                return
            
            df_table = df_filtered.copy()
            df_table['跟踪'] = df_table['keyword'].isin(fav_list)
            df_table['隐藏'] = False
            df_table['🎯 直达日亚前台'] = df_table['keyword'].apply(lambda k: f"https://www.amazon.co.jp/s?k={urllib.parse.quote(k)}")
            
            def mark_kw_status(row):
                return f"[🔴 已查] {row['keyword']}" if row['keyword'] in clicked_kws else row['keyword']
            df_table['日本站搜索关键词'] = df_table.apply(mark_kw_status, axis=1)
            
            df_table['今日排名'] = df_table['sfr_curr'].map("{:,.0f}".format)
            df_table['昨日排名'] = df_table['sfr_prev'].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "线外 (NEW)")
            df_table['名次提升'] = df_table['rank_jump'].apply(lambda x: "⚡ NEW空降" if x >= 900000 else f"▲ {x:,.0f}")
            df_table['涨幅%'] = df_table['growth_pct'].apply(lambda x: "NEW" if x >= 900 else f"+{x:.1f}%")
            df_table['Top1 ASIN'] = df_table['asin1']
            df_table['Top1 点击占比'] = df_table['c1'].map("{:.1f}%".format)
            df_table['Top1 承接力'] = df_table['top1_power'].apply(lambda x: "🐯 极弱(可抢)" if x < 0.85 else ("🛡️ 稳固" if x > 1.25 else "势均力敌"))
            
            col_list = ['跟踪', '日本站搜索关键词', '🎯 直达日亚前台', '今日排名', '昨日排名', '名次提升', '涨幅%', 'Top1 承接力', 'Top1 ASIN', 'Top1 点击占比', '隐藏']
            
            edited_grid = st.data_editor(
                df_table[col_list],
                column_config={
                    "跟踪": st.column_config.CheckboxColumn("关注", width="small"),
                    "🎯 直达日亚前台": st.column_config.LinkColumn("前台验款", display_text="直达搜索"),
                    "隐藏": st.column_config.CheckboxColumn("隐藏", width="small", help="不再关注该词")
                },
                disabled=[c for c in col_list if c not in ['跟踪', '隐藏']],
                use_container_width=True,
                height=480,
                key=f"{tab_key}_grid"
            )
            
            if st.session_state.get(f"{tab_key}_grid") and st.session_state[f"{tab_key}_grid"]["edited_rows"]:
                for row_idx, edit_val in st.session_state[f"{tab_key}_grid"]["edited_rows"].items():
                    target_kw = df_filtered.iloc[row_idx]['keyword']
                    if "隐藏" in edit_val and edit_val["隐藏"]:
                        st.session_state['temp_deleted_keywords'].add(target_kw)
                        remove_from_favorites(target_kw)
                        st.toast(f"已隐藏：{target_kw}")
                        st.rerun()
                    elif "跟踪" in edit_val:
                        if edit_val["跟踪"]:
                            add_to_favorites(target_kw)
                            st.toast(f"已添加至重点监控舱：{target_kw}")
                        else:
                            remove_from_favorites(target_kw)
                            st.toast(f"已移出监控：{target_kw}")
                        st.rerun()

        with tab_new:
            st.markdown("<p style='color:#64748B; font-size:13px;'>昨日未入榜，今日闪电入围的前沿需求（新品/季节性突发风向标）：</p>", unsafe_allow_html=True)
            render_clean_table(new_stars, "tab_new_view")

        with tab_jump:
            st.markdown("<p style='color:#64748B; font-size:13px;'>排名位次绝对提升最猛烈的关键词：</p>", unsafe_allow_html=True)
            render_clean_table(jumpers, "tab_jump_view")

        with tab_tiger:
            st.markdown("<p style='color:#64748B; font-size:13px;'>搜索量激增，但前三名竞品转化率极低，市场饥渴度高，极利于新产品切入抢单：</p>", unsafe_allow_html=True)
            render_clean_table(paper_tigers, "tab_tiger_view")

        with tab_fav:
            fav_df = surge_df[surge_df['keyword'].isin(fav_list)]
            st.markdown("<p style='color:#64748B; font-size:13px;'>您重点星标跟踪的关键词列表：</p>", unsafe_allow_html=True)
            render_clean_table(fav_df, "tab_fav_view")

        with tab_all:
            st.markdown("<p style='color:#64748B; font-size:13px;'>经过合规脱敏后的今日全量实物消费品大表：</p>", unsafe_allow_html=True)
            render_clean_table(surge_df, "tab_all_view")

        # 底部快捷动作区
        st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)
        act1, act2 = st.columns(2)
        with act1:
            st.markdown("##### 🎯 暴涨词 1 秒导出为精确广告组")
            quick_ad_words = list(set(new_stars['keyword'].tolist()[:25] + jumpers['keyword'].tolist()[:25]))
            st.text_area("复制直接填入广告后台 (Exact Match):", value="\n".join(quick_ad_words), height=110)
        with act2:
            st.markdown("##### 📥 下载清洗后的实物报表")
            csv_file = surge_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"导出 {latest_date} 纯净选品 CSV",
                data=csv_file,
                file_name=f"ABA_Clean_Surge_{latest_date}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )
    else:
        st.info("💡 暂无有效数据。")
else:
    st.info("👋 欢迎来到 日亚选品与暴涨雷达 Pro！\n\n📌 **使用指引**：在左侧拖入 **2 期** ABA 报表，系统将自动激活【今日暴涨红警雷达】。")
