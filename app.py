import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 공통 적용 기준 (수정된 상수 반영)
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# 1. 파일명 (형님이 올리신 파일명)
DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# 2. 고정 변수 (엑셀 값 무시하고 강제 적용)
CONST_TAX_RATE = 0.209       # 법인세 19% + 주민세 1.9%
CONST_PERIOD = 30            # 감가상각 30년

# 3. 비용 단가 (일괄 적용)
COST_MAINT_M = 8222          # 배관유지비 (원/m)
COST_ADMIN_HH = 6209         # 일반관리비 (원/전) - 주택용
COST_ADMIN_M = 13605         # 일반관리비 (원/m) - 업무/산업용

# --------------------------------------------------------------------------
# [함수] 초강력 데이터 전처리 (에러 원천 차단)
# --------------------------------------------------------------------------
def clean_column_names(df):
    """컬럼명의 줄바꿈(\n), 공백, 특수문자를 모두 제거"""
    df.columns = [str(c).replace("\n", "").replace(" ", "").replace("\t", "").strip() for c in df.columns]
    return df

def find_col(df, keywords):
    """
    여러 키워드 중 하나라도 포함된 컬럼을 찾음 (우선순위 순)
    예: ['배관투자', '투자금액'] 리스트를 주면 먼저 발견되는 것 선택
    """
    for col in df.columns:
        for kw in keywords:
            if kw in col:
                return col
    return None

def parse_value(value):
    """숫자만 추출 (에러 절대 안 나게 처리)"""
    try:
        if pd.isna(value) or value == '':
            return 0.0
        # 문자열로 변환 후 쉼표 제거
        clean_str = str(value).replace(',', '')
        # 숫자 추출
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers:
            return float(numbers[0])
        return 0.0
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수] 판관비 자동 분류 로직
# --------------------------------------------------------------------------
def calculate_sga(usage_str, length, households):
    """
    용도(usage_str)를 보고 관리비 적용 기준 결정
    """
    # 1. 배관유지비 (무조건 길이 비례)
    maint_cost = length * COST_MAINT_M
    
    # 2. 일반관리비 (용도별 분기)
    usage = str(usage_str).strip()
    
    # 주택용 키워드 (공동주택, 단독주택, 다가구, 아파트 등)
    # 엑셀 데이터를 보니 '공동주택', '단독주택' 등으로 적혀있음
    if any(k in usage for k in ['공동', '단독', '주택', '아파트', '주거']):
        admin_cost = households * COST_ADMIN_HH # 세대당 6209원
    else:
        # 그 외 (업무용, 산업용, 영업용 등)
        admin_cost = length * COST_ADMIN_M # m당 13605원
        
    return maint_cost + admin_cost

# --------------------------------------------------------------------------
# [함수] 역산 시뮬레이션
# --------------------------------------------------------------------------
def calculate_min_volume(df, target_irr):
    
    # PVIFA
    if target_irr == 0:
        pvifa = CONST_PERIOD
    else:
        pvifa = (1 - (1 + target_irr) ** (-CONST_PERIOD)) / target_irr

    results = []
    
    # [중요] 컬럼 찾기 (여러 키워드로 시도)
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    # 필수 컬럼 체크
    if not col_invest or not col_vol or not col_profit:
        return df, f"❌ 핵심 컬럼을 못 찾았습니다. (확인된 컬럼: {list(df.columns)})"

    # 계산 반복
    total_rows = len(df)
    progress_bar = st.progress(0, text="경제성 분석 진행 중...")

    for index, row in df.iterrows():
        try:
            # 1. 기초 데이터 파싱
            investment = parse_value(row.get(col_invest))
            contribution = parse_value(row.get(col_contrib))
            current_vol = parse_value(row.get(col_vol))
            current_profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            households = parse_value(row.get(col_hh))
            usage_str = row.get(col_usage, "")

            # 데이터 유효성 체크
            if current_vol <= 0 or investment <= 0:
                results.append(0)
                continue

            # 2. 역산 로직
            
            # (A) 순투자액
            net_investment = investment - contribution
            
            # (B) 자본회수 필요액 (Required OCF)
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # (C) 판관비 (용도별 자동 계산)
            total_sga = calculate_sga(usage_str, length, households)

            # (D) 감가상각비
            depreciation = investment / CONST_PERIOD

            # (E) 필요 세전이익 (EBIT)
            # OCF = (EBIT * (1-t)) + Dep
            required_ebit = (required_capital_recovery - depreciation) / (1 - CONST_TAX_RATE)

            # (F) 필요 마진총액 (Gross Margin)
            required_gross_margin = required_ebit + total_sga + depreciation

            # (G) 단위당 마진
            unit_margin = current_profit / current_vol
            if unit_margin <= 0:
                results.append(0)
                continue

            # (H) 목표 판매량
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

    return df, None

# --------------------------------------------------------------------------
# [UI 구성]
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")
st.markdown(f"**[적용 기준]** IRR 6.15% / 법인세 20.9% / 상각 30년 / 비용 일괄적용")

# 사이드바
with st.sidebar:
    st.header("📂 파일 선택")
    data_source = st.radio("소스 선택", ("GitHub 파일", "엑셀 업로드"))
    
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
        
    st.divider()
    st.write(f"배관유지비: {COST_MAINT_M}원/m")
    st.write(f"관리비(주택): {COST_ADMIN_HH}원/전")
    st.write(f"관리비(기타): {COST_ADMIN_M}원/m")

# 데이터 로드
df = None

if data_source == "GitHub 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ '{DEFAULT_FILE_NAME}' 로드 성공")
        except Exception as e:
            st.error(f"❌ 파일 읽기 에러: {e}")
    else:
        st.warning(f"⚠️ '{DEFAULT_FILE_NAME}' 파일이 없습니다. (파일명: 리스트_20260129.xlsx)")

elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    st.success("✅ 파일 업로드 성공")

# 결과 출력
if df is not None:
    # 1. 컬럼 정리 (줄바꿈 제거)
    df = clean_column_names(df)
    
    # 2. 계산
    result_df, error_msg = calculate_min_volume(df, 0.0615)
    
    if error_msg:
        st.error(error_msg)
        # 디버깅용: 현재 컬럼명 보여주기
        with st.expander("🔍 엑셀 컬럼명 확인하기 (디버깅)"):
            st.write(list(df.columns))
    else:
        st.subheader("📊 분석 결과")
        
        # 보여줄 컬럼
        view_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량계(MJ)", "최소경제성만족판매량", "달성률(%)"]
        # 실제 있는 것만 필터링
        final_cols = [c for c in view_cols if c in result_df.columns]
        
        # 스타일링 (최소판매량 강조)
        st.dataframe(
            result_df[final_cols].style.background_gradient(subset=['최소경제성만족판매량'], cmap="Oranges") if '최소경제성만족판매량' in result_df.columns else result_df[final_cols],
            use_container_width=True
        )
        
        # 다운로드
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False)
            writer.sheets['Sheet1'].set_column('A:Z', 18)
            
        st.download_button("📥 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
