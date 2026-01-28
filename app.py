import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정 1] 공통 적용 기준 (User Constraints)
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# 1. 파일명 설정
DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# 2. 세금 및 상각 기준 (일괄 적용)
CONST_TAX_RATE = 0.209       # 법인세 19% + 주민세 1.9%
CONST_PERIOD = 30            # 감가상각 30년

# 3. 비용 단가 (일괄 적용)
COST_MAINT_M = 8222          # 배관유지비 (원/m) - 모든 구간 공통
COST_ADMIN_HH = 6209         # 일반관리비 (원/전) - 주택용(공동/단독)
COST_ADMIN_M = 13605         # 일반관리비 (원/m)  - 비주택(산업/업무/영업)

# --------------------------------------------------------------------------
# [함수] 스마트 데이터 처리 (에러 방지)
# --------------------------------------------------------------------------
def clean_column_names(df):
    """컬럼명 공백 제거 및 문자열 변환"""
    df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
    return df

def find_col(df, keyword):
    """키워드로 컬럼 찾기"""
    for col in df.columns:
        if keyword in col:
            return col
    return None

def parse_value(value):
    """숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    clean_str = str(value).replace(',', '')
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

# --------------------------------------------------------------------------
# [함수] 판관비(SG&A) 계산 로직 (조건부 적용)
# --------------------------------------------------------------------------
def calculate_sga(row, length, households, col_usage):
    """
    용도에 따라 일반관리비 적용 기준을 달리함
    - 주택용(공동, 단독 등): 세대수 * 6,209원
    - 그 외(산업, 업무 등): 길이 * 13,605원
    - 배관유지비: 길이 * 8,222원 (공통)
    """
    # 1. 배관유지비 (무조건 길이 비례)
    maint_cost = length * COST_MAINT_M
    
    # 2. 일반관리비 (용도별 차등)
    usage = str(row.get(col_usage, "")).strip()
    admin_cost = 0.0
    
    # 주택용 키워드 감지
    if any(x in usage for x in ['공동', '단독', '주택', '아파트', '다가구']):
        admin_cost = households * COST_ADMIN_HH
    else:
        # 비주택(산업용, 업무용, 영업용 등)은 길이 비례 적용
        admin_cost = length * COST_ADMIN_M
        
    return maint_cost + admin_cost

# --------------------------------------------------------------------------
# [함수] 핵심 역산 로직
# --------------------------------------------------------------------------
def calculate_min_volume(df, target_irr):
    
    # PVIFA 계산
    if target_irr == 0:
        pvifa = CONST_PERIOD
    else:
        pvifa = (1 - (1 + target_irr) ** (-CONST_PERIOD)) / target_irr

    results = []
    
    # 컬럼 매칭 (스마트 검색)
    col_invest = find_col(df, "투자금액")
    col_contrib = find_col(df, "시설분담금")
    col_vol = find_col(df, "연간판매량")
    col_profit = find_col(df, "연간판매수익")
    col_len = find_col(df, "길이")
    col_hh = find_col(df, "계획전수") # 세대수
    col_usage = find_col(df, "용도")

    # [디버깅] 필수 컬럼 체크
    missing_cols = []
    if not col_invest: missing_cols.append("투자금액")
    if not col_vol: missing_cols.append("연간판매량")
    if not col_profit: missing_cols.append("연간판매수익")
    
    if missing_cols:
        st.error(f"❌ 엑셀 파일에서 다음 컬럼을 찾을 수 없습니다: {missing_cols}")
        st.stop()

    # 진행바
    progress_bar = st.progress(0, text="경제성 역산 시뮬레이션 중...")
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # A. 기초 데이터
            investment = parse_value(row.get(col_invest, 0))
            contribution = parse_value(row.get(col_contrib, 0))
            current_vol = parse_value(row.get(col_vol, 0))
            current_profit = parse_value(row.get(col_profit, 0))
            length = parse_value(row.get(col_len, 0))
            households = parse_value(row.get(col_hh, 0))

            if current_vol <= 0 or investment <= 0:
                results.append(0)
                continue

            # B. 역산 로직
            
            # 1. 순투자액
            net_investment = investment - contribution
            
            # 2. 자본회수 필요액 (Required OCF)
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 3. 연간 판관비 (조건부 계산 적용)
            total_sga = calculate_sga(row, length, households, col_usage)

            # 4. 감가상각비
            depreciation = investment / CONST_PERIOD

            # 5. 필요 세전이익 (Required EBIT)
            # OCF = (EBIT * (1-t)) + Dep
            required_ebit = (required_capital_recovery - depreciation) / (1 - CONST_TAX_RATE)

            # 6. 필요 공헌이익 (Gross Margin)
            required_gross_margin = required_ebit + total_sga + depreciation

            # 7. 단위당 마진
            unit_margin = current_profit / current_vol
            if unit_margin <= 0:
                results.append(0)
                continue

            # 8. 목표 판매량
            required_volume = required_gross_margin / unit_margin
            results.append(max(0, round(required_volume, 2)))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    
    # 달성률
    df['달성률(%)'] = df.apply(lambda x: round((x[col_vol] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 else 999.9, axis=1)

    return df

# --------------------------------------------------------------------------
# [UI 구성] 사이드바
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 데이터 파일")
    data_source = st.radio("파일 소스", ("GitHub 기본 파일", "엑셀 업로드"), index=0)
    
    uploaded_file = None
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 선택 (.xlsx)", type=['xlsx'])

    st.divider()
    st.subheader("⚙️ 고정 분석 기준")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    
    st.info(f"""
    **[적용된 비용/세율]**
    * 세금: {CONST_TAX_RATE*100:.1f}%
    * 상각: {CONST_PERIOD}년
    * 유지비: {COST_MAINT_M:,}원/m
    * 관리비(주택): {COST_ADMIN_HH:,}원/전
    * 관리비(기타): {COST_ADMIN_M:,}원/m
    """)

# --------------------------------------------------------------------------
# [UI 구성] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")
st.markdown(f"""
**[분석 개요]**
* **목표:** 기존 투자 건(2020~2024)에 대해 IRR 6.15% 달성용 **최소 판매량** 산출
* **비용 적용:** 엑셀 데이터 대신 **고정 단가(유지비 8,222원 등)**를 일괄 적용
* **대상 파일:** `{DEFAULT_FILE_NAME}`
""")
st.divider()

# 데이터 로드 로직
df = None

if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ '{DEFAULT_FILE_NAME}' 로드 성공!")
        except Exception as e:
            st.error(f"❌ 파일 읽기 에러: {e}")
    else:
        st.error(f"⚠️ 중요: 깃허브 저장소에 '{DEFAULT_FILE_NAME}' 파일이 없습니다!")
        st.info("👉 깃허브에 파일을 업로드하시거나, 좌측 사이드바에서 '엑셀 업로드'를 이용해주세요.")

elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    st.success("✅ 파일 업로드 성공!")

# 결과 출력
if df is not None:
    df = clean_column_names(df)
    result_df = calculate_min_volume(df, target_irr)
    
    st.subheader("📊 분석 결과: 최소경제성만족판매량")
    
    # 표시 컬럼
    key_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률"]
    display_cols = [find_col(result_df, k) for k in key_cols if find_col(result_df, k)]
            
    if display_cols:
        target_col = find_col(result_df, "최소경제성만족판매량")
        st.dataframe(
            result_df[display_cols].style.background_gradient(subset=[target_col], cmap="Oranges"),
            use_container_width=True
        )

    # 다운로드
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 18)
        
    st.download_button(
        label="📥 결과 엑셀 다운로드 (Click)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_분석결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
