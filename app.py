import streamlit as st
import pandas as pd
import numpy as np
import re
import io

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --- 제목 및 안내 ---
st.title("💰 도시가스 배관투자 경제성 분석기 (IRR 6.15%)")
st.markdown("""
이 도구는 **기존 투자 건**에 대해, 목표 수익률(IRR 6.15%)을 달성하기 위한 **최소 판매량(BEP Volume)**을 역산합니다.
* **필수 포함 컬럼:** 배관투자금액, 총시설분담금, 연간판매량계(MJ), 연간판매수익, 길이, 계획전수, 연간 배관유지비, 연간 일반관리비
""")

# --- 함수 정의 ---

def clean_column_names(df):
    """컬럼명 앞뒤 공백 제거"""
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 문자열에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    # 문자열로 변환 후, 숫자와 소수점(.)만 남기고 다 제거
    clean_str = str(value).replace(',', '')
    numbers = re.findall(r"[\d\.]+", clean_str)
    
    if numbers:
        # 추출된 것 중 첫 번째 숫자를 사용
        return float(numbers[0])
    return 0.0

def calculate_irr_target(df):
    # 사이드바 설정 (나중에 기준 바뀌면 여기서 수정 가능)
    with st.sidebar:
        st.header("⚙️ 분석 파라미터")
        TARGET_IRR = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
        TAX_RATE = st.number_input("세율 (법인세+주민세, %)", value=20.9, format="%.1f") / 100
        PERIOD = st.number_input("감가상각 기간 (년)", value=30)

    # 연금현가계수(PVIFA) 미리 계산
    if TARGET_IRR == 0:
        pvifa = PERIOD
    else:
        pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    
    # 진행 상황바
    progress_bar = st.progress(0)
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # 1. 기초 데이터 추출 (안전하게 .get 사용)
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) 
            
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            # 2. 판관비 파싱 (문자열 -> 숫자)
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            # 산업용 등을 위한 예비 컬럼 (없으면 0 처리됨)
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            # --- 예외 처리 (데이터 불량) ---
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- 핵심 계산 로직 ---

            # A. 순투자액
            net_investment = investment - contribution
            
            # 시설분담금으로 투자비 전액 회수 시 분석 불필요
            if net_investment <= 0:
                results.append(0) 
                continue

            # B. 연간 판관비 (SG&A)
            # 관리비는 세대수 기준 우선, 없으면 길이 기준(산업용 등) 적용 가능하게 합산
            annual_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)

            # C. 단위당 마진 (MJ당 공헌이익)
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # D. 감가상각비 (정액법)
            depreciation = investment / PERIOD

            # E. 목표 현금흐름(OCF) 역산 (Net Investment = OCF * PVIFA)
            required_ocf = net_investment / pvifa

            # F. 필요 총이익(Gross Margin) 역산
            # 세후OCF -> 세전이익 환산 -> 판관비/상각비 더하기
            required_pretax_profit = (required_ocf - depreciation) / (1 - TAX_RATE)
            required_gross_margin = required_pretax_profit + annual_sga + depreciation

            # G. 최종 목표 판매량
            required_volume = required_gross_margin / unit_margin
            
            results.append(round(required_volume, 2))

        except Exception:
            results.append(0)
        
        # 진행바 업데이트
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    return df

# --- 메인 화면 UI ---
file = st.file_uploader("📂 엑셀 파일을 업로드하세요 (리스트_20260128.xlsx)", type=['xlsx'])

if file is not None:
    st.success("파일 업로드 성공! 분석을 시작합니다...")
    
    try:
        # 엑셀 읽기
        df = pd.read_excel(file)
        df = clean_column_names(df) # 컬럼 공백 제거

        # 계산 실행
        result_df = calculate_irr_target(df)
        
        st.divider()
        st.subheader("📊 분석 결과 확인")
        
        # 주요 컬럼만 미리보기
        preview_cols = ['투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량']
        # 존재하는 컬럼만 필터링해서 보여주기
        valid_cols = [c for c in preview_cols if c in result_df.columns]
        st.dataframe(result_df[valid_cols].head(50))

        # 다운로드 버튼
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False)
        
        st.download_button(
            label="📥 전체 분석 결과 다운로드 (Excel)",
            data=output.getvalue(),
            file_name="경제성분석_결과_IRR6.15.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")
        st.warning("엑셀 파일의 형식이 맞는지, 필수 컬럼이 있는지 확인해주세요.")
