import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# -----------------------------------------------------------
# [설정] 깃허브에 올린 엑셀 파일 이름 (정확해야 함!)
# -----------------------------------------------------------
TARGET_FILE_NAME = "리스트_20260128.xlsx" 

# 페이지 설정
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")
st.title("💰 도시가스 배관투자 경제성 역산 분석기")
st.markdown(f"""
**[분석 개요]**
* **목표:** 기 투자된 구간(2020~2024)의 투자 효율성 검증
* **기준:** IRR 6.15% 달성을 위한 **최소 연간 판매량(BEP Volume)** 산출
* **조건:** 상각 30년, 법인세+주민세 20.9% 적용
""")

# --- [함수 1] 데이터 전처리 ---
def clean_column_names(df):
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 텍스트에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    clean_str = str(value).replace(',', '')
    # 숫자와 소수점만 찾기
    numbers = re.findall(r"[\d\.]+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

# --- [함수 2] 핵심 역산 로직 (Goal Seek) ---
def calculate_target_volume(df):
    # 사이드바에서 기준 변경 가능
    with st.sidebar:
        st.header("⚙️ 분석 기준 설정")
        TARGET_IRR = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
        TAX_RATE = st.number_input("세율 (20.9%)", value=20.9, format="%.1f") / 100
        PERIOD = st.number_input("감가상각 기간 (년)", value=30)
    
    # 1. 연금현가계수 (PVIFA) 계산
    # 매년 동일한 현금흐름(PMT)이 30년간 발생할 때, 현재가치로 환산하는 계수
    if TARGET_IRR == 0:
        pvifa = PERIOD
    else:
        pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    
    # 진행률바
    progress_bar = st.progress(0)
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # --- A. 데이터 추출 (컬럼명 유연하게 처리) ---
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) # 마진 총액 (Sales - COGS)
            
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            # 판관비 단가 추출 (문자열 -> 숫자 변환)
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0)) # 산업용 등 대비

            # --- B. 예외 처리 ---
            # 판매량이 없거나 투자비가 없으면 계산 불가
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- C. 역산 로직 시작 ---
            
            # 1. 순투자액 (Net Investment) = 초기 현금 유출
            net_investment = investment - contribution
            
            # 시설분담금이 투자비보다 크면(이미 이득), 최소 판매량은 0 (또는 유지비만 건지면 됨)
            if net_investment <= 0:
                results.append(0) 
                continue

            # 2. 목표 달성을 위해 매년 회수해야 할 '세후 영업현금흐름(OCF)'
            # 공식: Net Investment = OCF * PVIFA
            required_ocf = net_investment / pvifa

            # 3. 연간 총 판관비 (SG&A) 계산
            annual_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # 4. 연간 감가상각비
            depreciation = investment / PERIOD

            # 5. 필요한 '세전 이익(Pre-tax Profit)' 역산
            # OCF = (EBIT * (1-t)) + Dep
            # EBIT(세전이익) = (OCF - Dep) / (1-t)
            required_pretax_profit = (required_ocf - depreciation) / (1 - TAX_RATE)

            # 6. 필요한 '총 공헌이익(Gross Margin)' 역산
            # 세전이익 = 공헌이익 - 판관비 - 감가상각비
            # 공헌이익 = 세전이익 + 판관비 + 감가상각비
            required_gross_margin = required_pretax_profit + annual_sga + depreciation

            # 7. 단위당 마진 (MJ당 수익)
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # 8. 최종 목표 판매량 (Q)
            # Q = 필요 공헌이익 / 단위당 마진
            required_volume = required_gross_margin / unit_margin
            
            results.append(round(required_volume, 2))

        except Exception:
            results.append(0)
        
        # 진행률 업데이트
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    
    # 결과 컬럼 생성
    df['최소경제성만족판매량'] = results
    
    # [추가] 달성률 계산 (현재판매량 / 목표판매량)
    df['달성률(%)'] = df.apply(lambda x: round((x['연간판매량계(MJ)'] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 else 0, axis=1)
    
    return df

# --- 메인 화면 로직 ---
df = None
file_source = ""

col1, col2 = st.columns([1, 2])

with col1:
    st.info("📂 **파일 로딩 상태**")
    # 1. 깃허브(로컬)에 파일이 있는지 확인
    if os.path.exists(TARGET_FILE_NAME):
        st.success(f"'{TARGET_FILE_NAME}' 발견!")
        if st.button("🚀 깃허브 파일로 분석 실행", type="primary"):
            try:
                df = pd.read_excel(TARGET_FILE_NAME)
                file_source = "GitHub"
            except Exception as e:
                st.error(f"파일 읽기 오류: {e}")
    else:
        st.warning("깃허브에 지정된 파일이 없습니다.")

with col2:
    # 2. 없거나 다른 파일 쓰고 싶을 때 업로드
    uploaded_file = st.file_uploader("또는 내 컴퓨터의 엑셀 파일 업로드", type=['xlsx'])
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
        file_source = "Upload"

# --- 결과 출력 ---
if df is not None:
    df = clean_column_names(df)
    
    # 계산 수행
    result_df = calculate_target_volume(df)
    
    st.divider()
    st.subheader(f"📊 분석 결과 (Source: {file_source})")
    
    # 결과 미리보기 (주요 컬럼만)
    preview_cols = ['투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량', '달성률(%)']
    valid_cols = [c for c in preview_cols if c in result_df.columns]
    
    # 데이터프레임 스타일링 (목표 미달 구간 빨간색 표시 등)
    st.dataframe(result_df[valid_cols].head(100), use_container_width=True)

    # 엑셀 다운로드
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 15) # 너비 조정
    
    st.download_button(
        label="📥 분석 결과 엑셀 다운로드",
        data=output.getvalue(),
        file_name="경제성분석_최소판매량_결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
