import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# ==============================================================================
# [설정] 깃허브에 올린 엑셀 파일 이름 (확장자까지 정확해야 합니다)
TARGET_FILE_NAME = "리스트_20260128.xlsx"
# ==============================================================================

st.title("💰 도시가스 배관투자 경제성 분석기 (IRR 6.15%)")
st.markdown("깃허브에 함께 저장된 **리스트 파일**을 자동으로 읽거나, 새 파일을 업로드합니다.")

# --- 함수 정의 ---
def clean_column_names(df):
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
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

    if TARGET_IRR == 0:
        pvifa = PERIOD
    else:
        pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    progress_bar = st.progress(0)
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) 
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            net_investment = investment - contribution
            if net_investment <= 0:
                results.append(0) 
                continue

            annual_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

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
use_local_file = False

col1, col2 = st.columns([1, 1])

with col1:
    st.info("📂 **기본 파일 사용**")
    # 버튼을 누르면 같은 폴더에 있는 파일을 읽습니다.
    if st.button("🚀 깃허브에 있는 파일로 분석하기"):
        if os.path.exists(TARGET_FILE_NAME):
            try:
                df = pd.read_excel(TARGET_FILE_NAME)
                use_local_file = True
                st.success(f"'{TARGET_FILE_NAME}' 파일을 성공적으로 읽었습니다!")
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
        else:
            st.error(f"⚠️ '{TARGET_FILE_NAME}' 파일이 없습니다. 깃허브 파일 목록에 이 이름이 있는지 확인해주세요.")

with col2:
    st.info("💻 **내 컴퓨터 파일 사용**")
    uploaded_file = st.file_uploader("새로운 엑셀 파일 업로드", type=['xlsx'])
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
        use_local_file = False

# --- 결과 출력 ---
if df is not None:
    df = clean_column_names(df)
    result_df = calculate_irr_target(df)
    
    st.divider()
    source_text = "GitHub Saved File" if use_local_file else "Uploaded File"
    st.subheader(f"📊 분석 결과 (Source: {source_text})")

    cols = ['투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량']
    valid_cols = [c for c in cols if c in result_df.columns]
    st.dataframe(result_df[valid_cols].head(50))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
    
    st.download_button(
        label="📥 결과 엑셀 다운로드",
        data=output.getvalue(),
        file_name="경제성분석_결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
