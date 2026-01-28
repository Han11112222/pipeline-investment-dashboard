import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import requests

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# ==============================================================================
# [중요] 형님의 깃허브 파일 주소 ("Raw" 주소여야 합니다!)
# 따는 법: 깃허브 파일 클릭 -> 'Download' 아이콘 우클릭 -> '링크 주소 복사'
# ==============================================================================
GITHUB_FILE_URL = "https://github.com/Han-User/gas-irr-analysis/raw/main/리스트_20260128.xlsx" 
# (위 주소는 예시입니다. 형님의 실제 주소로 꼭 바꿔주세요!)

st.title("💰 도시가스 배관투자 경제성 분석기 (IRR 6.15%)")
st.markdown("깃허브에 저장된 **최신 리스트 파일**을 불러오거나, 개별 파일을 업로드하여 분석합니다.")

# --- 함수 정의 ---
def clean_column_names(df):
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 문자열에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    clean_str = str(value).replace(',', '')
    numbers = re.findall(r"[\d\.]+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

def calculate_irr_target(df):
    with st.sidebar:
        st.header("⚙️ 분석 파라미터")
        TARGET_IRR = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
        TAX_RATE = st.number_input("세율 (20.9%)", value=20.9, format="%.1f") / 100
        PERIOD = st.number_input("상각 기간 (30년)", value=30)

    # PVIFA 계산
    if TARGET_IRR == 0:
        pvifa = PERIOD
    else:
        pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    progress_bar = st.progress(0)
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # 1. 데이터 추출
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) 
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            # 2. 판관비 추출
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            # 예외 처리
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # A. 순투자액
            net_investment = investment - contribution
            if net_investment <= 0:
                results.append(0) 
                continue

            # B. 판관비 합산 (세대수 기준 + 길이 기준)
            annual_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)

            # C. 단위 마진
            unit_margin = current_sales_profit / current_sales_volume
            if unit_margin <= 0:
                results.append(0)
                continue

            # D. 역산 로직
            depreciation = investment / PERIOD
            required_ocf = net_investment / pvifa
            required_pretax_profit = (required_ocf - depreciation) / (1 - TAX_RATE)
            required_gross_margin = required_pretax_profit + annual_sga + depreciation
            
            required_volume = required_gross_margin / unit_margin
            results.append(round(required_volume, 2))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    return df

# --- 메인 실행 로직 ---
df = None
use_github = False

col1, col2 = st.columns([1, 1])

with col1:
    st.info("☁️ **클라우드 파일 사용**")
    if st.button("🚀 깃허브 리스트 파일 불러오기"):
        try:
            with st.spinner('깃허브에서 파일 다운로드 중...'):
                response = requests.get(GITHUB_FILE_URL)
                response.raise_for_status()
                df = pd.read_excel(io.BytesIO(response.content))
                use_github = True
                st.success("성공! 깃허브 파일을 불러왔습니다.")
        except Exception as e:
            st.error(f"실패했습니다. URL을 확인해주세요.\n에러: {e}")

with col2:
    st.info("💻 **내 컴퓨터 파일 사용**")
    uploaded_file = st.file_uploader("파일 직접 업로드", type=['xlsx'])
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
        use_github = False

# --- 결과 출력 ---
if df is not None:
    df = clean_column_names(df)
    result_df = calculate_irr_target(df)
    
    st.divider()
    source_text = "GitHub File" if use_github else "Uploaded File"
    st.subheader(f"📊 분석 결과 (Source: {source_text})")

    # 주요 컬럼 미리보기
    cols = ['투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량']
    valid_cols = [c for c in cols if c in result_df.columns]
    st.dataframe(result_df[valid_cols].head(50))

    # 다운로드
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
    
    st.download_button(
        label="📥 결과 엑셀 다운로드",
        data=output.getvalue(),
        file_name="경제성분석_결과_IRR6.15.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
