import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# [설정] 깃허브에 올린 파일명 (정확해야 합니다)
DEFAULT_FILE_NAME = "리스트_20260128.xlsx"

# --- [함수] 데이터 전처리 (숫자만 추출) ---
def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 텍스트에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    # 문자열로 변환 후 쉼표 제거
    clean_str = str(value).replace(',', '')
    # 숫자와 소수점만 남기고 나머지 제거
    numbers = re.findall(r"[\d\.]+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

def clean_column_names(df):
    """컬럼명 앞뒤 공백 제거"""
    df.columns = [c.strip() for c in df.columns]
    return df

# --- [함수] 핵심 역산 로직 ---
def calculate_target_volume(df, target_irr, tax_rate, period):
    
    # 1. 연금현가계수 (PVIFA)
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 진행률 표시
    progress_bar = st.progress(0, text="회사 내부 로직(세후OCF 역산) 적용 중...")
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # --- A. 데이터 추출 (안전하게 가져오기) ---
            # 투자비
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            # 시설분담금
            contribution = float(row.get('총시설분담금', 0))
            # 순투자액
            net_investment = investment - contribution

            # 현재 판매량 및 수익
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) 
            
            # 길이 및 세대수
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            # 판관비 단가 (텍스트에서 숫자 파싱)
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            # --- B. 예외 처리 ---
            # 판매량이 0이거나 데이터가 없으면 계산 불가 -> 0 처리
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- C. 역산 시뮬레이션 (Reverse Engineering) ---
            
            # 1. 목표 달성 필요 현금흐름 (Required OCF)
            # 순투자액이 0보다 작으면(분담금으로 이미 회수), 추가 회수 필요 없음 -> 0
            if net_investment <= 0:
                required_ocf = 0
            else:
                required_ocf = net_investment / pvifa

            # 2. 연간 총 판관비 (Total SG&A)
            # (길이 x m당 유지비) + (세대수 x 전당 관리비) + (길이 x m당 관리비_산업용 등)
            total_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # 3. 감가상각비 (Depreciation)
            depreciation = investment / period

            # 4. 필요 공헌이익(Gross Margin) 역산
            # 공식: GP = [ (OCF - Dep) / (1 - Tax) ] + SGA + Dep
            # 설명: 세후현금흐름에서 감가상각비를 빼고 세율을 역산하면 '세전이익'이 됨. 
            #       거기에 판관비와 감가상각비를 더하면 매출총이익(공헌이익)이 됨.
            
            required_pretax_profit = (required_ocf - depreciation) / (1 - tax_rate)
            required_gross_margin = required_pretax_profit + total_sga + depreciation

            # 5. 단위당 마진 (MJ당 수익)
            # 현재 엑셀의 '연간판매수익'을 기준으로 함
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # 6. 최종 목표 판매량 (Target Volume)
            required_volume = required_gross_margin / unit_margin
            
            # 음수가 나오면 0으로 처리 (이미 수익성 충분함)
            results.append(max(0, round(required_volume, 2)))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    
    # [추가] 달성률 계산 (현재 판매량이 목표의 몇 %인지)
    df['달성률(%)'] = df.apply(lambda x: round((x['연간판매량계(MJ)'] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 else 999.9, axis=1)
    
    return df

# =========================================================
# [UI 구성] 사이드바
# =========================================================
with st.sidebar:
    st.header("📂 데이터 설정")
    data_source = st.radio("파일 선택", ("GitHub 기본 파일", "엑셀 업로드"), index=0)
    
    uploaded_file = None
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 올리기 (.xlsx)", type=['xlsx'])
    
    st.divider()
    st.subheader("⚙️ 분석 기준 (IRR 6.15%)")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    tax_rate = st.number_input("세율 (법인세+주민세, %)", value=20.9, format="%.1f") / 100
    period = st.number_input("상각 기간 (년)", value=30)

# =========================================================
# [UI 구성] 메인 화면
# =========================================================
st.title("💰 도시가스 배관투자 경제성 분석기")
st.markdown("""
### 📝 분석 개요
기존 투자 건(2020~2024)에 대하여 **IRR 6.15%를 달성하기 위한 최소 판매량(BEP)**을 산출합니다.
* **계산 로직:** 회사의 '투자경제성분석서(NPV/IRR)'와 동일한 로직(세후 영업현금흐름 역산)을 적용했습니다.
* **활용 인자:** 투자비, 시설분담금, 연간 판관비(유지비/일반관리비), 감가상각비, 법인세 효과 등.
""")
st.divider()

# 데이터 로드
df = None
if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ 깃허브 파일 '{DEFAULT_FILE_NAME}' 로드 성공!")
        except Exception as e:
            st.error(f"파일 읽기 에러: {e}")
    else:
        st.warning(f"⚠️ '{DEFAULT_FILE_NAME}' 파일이 없습니다. 엑셀 파일을 업로드해주세요.")
elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')

# 결과 출력
if df is not None:
    df = clean_column_names(df)
    result_df = calculate_target_volume(df, target_irr, tax_rate, period)
    
    st.subheader("📊 분석 결과: 최소경제성만족판매량")
    
    # 주요 컬럼 선택 및 표시
    cols = ['공사관리번호', '투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량', '달성률(%)']
    valid_cols = [c for c in cols if c in result_df.columns]
    
    st.dataframe(
        result_df[valid_cols].style.background_gradient(subset=['최소경제성만족판매량'], cmap="Oranges"),
        use_container_width=True,
        height=500
    )

    # 다운로드 버튼
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        # 엑셀 서식 조정
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 15)
        
    st.download_button(
        label="📥 결과 엑셀 다운로드 (전체 데이터)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_분석결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
