import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")
st.title("💰 도시가스 배관투자 경제성 분석기 (IRR 6.15%)")

# [설정] 깃허브에 올린 엑셀 파일 이름
TARGET_FILE_NAME = "리스트_20260128.xlsx"

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
    # 상수 설정 (사이드바에서 변경 가능)
    with st.sidebar:
        st.header("⚙️ 분석 기준 설정")
        TARGET_IRR = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
        TAX_RATE = st.number_input("세율 (20.9%)", value=20.9, format="%.1f") / 100
        PERIOD = st.number_input("상각 기간 (30년)", value=30)

    # 연금현가계수(PVIFA)
    if TARGET_IRR == 0:
        pvifa = PERIOD
    else:
        pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    
    # 계산 진행률 표시
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

            # 2. 판관비 파싱
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            # 예외처리
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # A. 순투자액
            net_investment = investment - contribution
            if net_investment <= 0:
                results.append(0)
                continue

            # B. 판관비 합산
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

# 1. 파일 읽기 (깃허브 파일 우선, 없으면 업로드 창 표시)
if os.path.exists(TARGET_FILE_NAME):
    st.info(f"📂 깃허브에 있는 '{TARGET_FILE_NAME}' 파일을 불러와서 분석합니다.")
    try:
        df = pd.read_excel(TARGET_FILE_NAME)
    except Exception as e:
        st.error(f"파일 읽기 실패: {e}")
else:
    st.warning(f"⚠️ '{TARGET_FILE_NAME}' 파일이 없습니다. 엑셀 파일을 직접 업로드해주세요.")
    uploaded_file = st.file_uploader("엑셀 파일 업로드", type=['xlsx'])
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)

# 2. 결과 보여주기 & 다운로드
if df is not None:
    # 컬럼 정리 및 계산
    df = clean_column_names(df)
    result_df = calculate_irr_target(df)
    
    st.divider()
    st.subheader("📊 분석 결과 (미리보기)")
    
    # [핵심] 사용자가 보고 싶어하는 주요 컬럼만 골라서 보여주기
    # '최소경제성만족판매량' 컬럼을 맨 앞으로 가져와서 강조
    cols = ['공사관리번호', '투자분석명', '최소경제성만족판매량', '연간판매량계(MJ)', '용도']
    # 실제 파일에 있는 컬럼만 필터링
    valid_cols = [c for c in cols if c in result_df.columns]
    
    # 화면에 데이터프레임 표시 (하이라이트 기능 추가)
    st.dataframe(
        result_df[valid_cols].style.background_gradient(subset=['최소경제성만족판매량'], cmap="Oranges"),
        use_container_width=True
    )

    # 3. 엑셀 다운로드 버튼 만들기
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        # 엑셀 시트 너비 조정 (옵션)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 15)

    st.download_button(
        label="📥 분석 결과 엑셀 다운로드 (Click)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"  # 버튼 강조
    )
