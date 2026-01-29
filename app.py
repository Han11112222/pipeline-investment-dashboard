import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# --------------------------------------------------------------------------
# [함수] 데이터 전처리 & 파싱 (공통)
# --------------------------------------------------------------------------
def clean_column_names(df):
    """컬럼명 정규화"""
    df.columns = [str(c).replace("\n", "").replace(" ", "").replace("\t", "").strip() for c in df.columns]
    return df

def find_col(df, keywords):
    for col in df.columns:
        for kw in keywords:
            if kw in col:
                return col
    return None

def parse_value(value):
    try:
        if pd.isna(value) or value == '':
            return 0.0
        clean_str = str(value).replace(',', '')
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers:
            return float(numbers[0])
        return 0.0
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수] 1. 기존 분석 로직 (관리용)
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override=None):
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    margin_debug = [] 
    
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    if not col_invest or not col_vol or not col_profit:
        return df, [], "❌ 핵심 컬럼 미발견"

    for index, row in df.iterrows():
        try:
            investment = parse_value(row.get(col_invest))
            contribution = parse_value(row.get(col_contrib))
            current_vol = parse_value(row.get(col_vol))
            current_profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            households = parse_value(row.get(col_hh))
            usage_str = row.get(col_usage, "")

            if current_vol <= 0 or investment <= 0:
                results.append(0)
                margin_debug.append(0)
                continue

            net_investment = investment - contribution
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 기존 데이터 분석용 (엑셀 일괄 처리)
            maint_cost = length * cost_maint_m
            
            # 기존 데이터는 용도에 따라 분기 처리 (기존 로직 유지)
            if any(k in str(usage_str) for k in ['공동', '단독', '주택', '아파트']):
                admin_cost = households * cost_admin_hh
            else:
                admin_cost = length * cost_admin_m
            total_sga = maint_cost + admin_cost
            
            depreciation = investment / period
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            required_gross_margin = required_ebit + total_sga + depreciation
            
            calculated_margin = current_profit / current_vol
            if margin_override and margin_override > 0:
                final_margin = margin_override
            else:
                final_margin = calculated_margin

            if final_margin <= 0:
                results.append(0)
                margin_debug.append(0)
                continue

            required_volume = required_gross_margin / final_margin
            results.append(max(0, required_volume))
            margin_debug.append(final_margin)

        except:
            results.append(0)
            margin_debug.append(0)
    
    df['최소경제성만족판매량'] = results
    df['적용마진(원)'] = margin_debug
    
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, results, None

# --------------------------------------------------------------------------
# [함수] 2. 신규 시뮬레이션 로직 (무조건 3가지 합산, 에러 방지)
# --------------------------------------------------------------------------

def calculate_internal_irr(cash_flows, guess=0.1):
    """IRR 안전 계산 함수"""
    rate = guess
    for _ in range(100):
        npv = sum([cf / ((1+rate)**t) for t, cf in enumerate(cash_flows)])
        if abs(npv) < 1e-6: return rate
        d_npv = sum([-t * cf / ((1+rate)**(t+1)) for t, cf in enumerate(cash_flows)])
        if d_npv == 0: return 0
        rate -= npv / d_npv
    return rate if abs(rate) < 100 else 0

def simulate_project(inv_len, inv_amt, contrib, other_profit, vol, rev, cost, 
                     num_jeon, discount_rate, tax_rate, period,
                     cost_maint, cost_admin_jeon, cost_admin_m):
    
    # 1. 기초 데이터
    profit = rev - cost
    net_inv = inv_amt - contrib
    
    # 2. 판관비 계산 (형님 요청: 선택 없이 무조건 3가지 다 더함)
    # 변수명 혼동 방지를 위해 명확하게 매칭
    
    # (1) 배관 유지비 (m당)
    cost_1 = inv_len * cost_maint        
    
    # (2) 일반 관리비 (m당) -> 용도 상관없이 무조건 부과
    cost_2 = inv_len * cost_admin_m      
    
    # (3) 일반 관리비 (전당) -> 용도 상관없이 무조건 부과
    cost_3 = num_jeon * cost_admin_jeon  
    
    # 총 판관비 합계
    total_sga = cost_1 + cost_2 + cost_3
    
    # 3. 감가상각 & OCF
    dep = inv_amt / period
    ebit = (profit + other_profit) - total_sga - dep
    nopat = ebit * (1 - tax_rate)
    ocf = nopat + dep
    
    # 4. 현금흐름
    cash_flows = [-net_inv] + [ocf] * int(period)
    
    # 5. 지표 계산
    npv = sum([cf / ((1 + discount_rate) ** t) for t, cf in enumerate(cash_flows)])
    irr = calculate_internal_irr(cash_flows)
    
    dpp = 999
    cum_discounted_cf = 0
    for t, cf in enumerate(cash_flows):
        dc = cf / ((1 + discount_rate) ** t)
        cum_discounted_cf += dc
        if t > 0 and cum_discounted_cf >= 0:
            prev_cum = cum_discounted_cf - dc
            if dc != 0:
                fraction = abs(prev_cum) / dc
                dpp = (t - 1) + fraction
            else:
                dpp = t
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv, "ocf": ocf, "margin": profit, 
        "sga": total_sga, "ebit": ebit, "flows": cash_flows,
        "c1": cost_1, "c2": cost_2, "c3": cost_3
    }

# ==========================================================================
# [메인] 화면 구성
# ==========================================================================

with st.sidebar:
    st.header("📌 메뉴 선택")
    page_mode = st.radio("작업 모드:", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()

# --------------------------------------------------------------------------
# [화면 1] 관리 (기존)
# --------------------------------------------------------------------------
if page_mode == "배관투자 경제성 분석 관리":
    with st.sidebar:
        st.subheader("📂 파일 설정")
        data_source = st.radio("소스", ("GitHub 파일", "엑셀 업로드"))
        uploaded_file = None
        if data_source == "엑셀 업로드":
            uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
        
        st.divider()
        st.subheader("⚙️ 분석 기준")
        target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
        tax_rate_percent = st.number_input("세율 (%)", value=20.9, format="%.1f", step=0.1)
        period_input = st.number_input("상각 기간 (년)", value=30, step=1)
        
        st.subheader("💰 비용 단가 (2024년 기준)")
        cost_maint_m_input = st.number_input("유지비 (원/m)", value=8222)
        cost_admin_hh_input = st.number_input("일반관리비 (원/전)", value=6209)
        cost_admin_m_input = st.number_input("일반관리비 (원/m)", value=13605)

        st.divider()
        st.subheader("🔧 정밀 보정")
        margin_override_input = st.number_input("단위당 마진 강제 (원/MJ)", value=0.0, step=0.0001, format="%.4f")
        st.caption("* 0이면 자동 계산")

        target_irr = target_irr_percent / 100
        tax_rate = tax_rate_percent / 100

    st.title("💰 배관투자 경제성 분석 관리")
    st.markdown("💡 **기존 투자 건(2020~2024)에 대한 최소 판매량 및 달성률 분석**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("목표 IRR", f"{target_irr_percent:.2f}%")
    c2.metric("적용 세율", f"{tax_rate_percent}%")
    c3.metric("유지비", f"{cost_maint_m_input:,}원")
    c4.metric("적용 마진", f"{margin_override_input:.4f}" if margin_override_input > 0 else "자동")

    df = None
    if data_source == "GitHub 파일":
        if os.path.exists(DEFAULT_FILE_NAME):
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
        else:
            st.warning(f"⚠️ {DEFAULT_FILE_NAME} 없음")
    elif data_source == "엑셀 업로드" and uploaded_file:
        df = pd.read_excel(uploaded_file, engine='openpyxl')

    if df is not None:
        df = clean_column_names(df)
        
        result_df, margins, msg = calculate_all_rows(
            df, target_irr, tax_rate, period_input, 
            cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input,
            margin_override_input
        )
        
        if msg:
            st.error(msg)
        else:
            st.divider()
            st.subheader("📊 분석 결과")
            
            view_cols_map = {
                "공사관리번호": ["공사관리번호", "관리번호"],
                "투자분석명": ["투자분석명", "공사명"],
                "용도": ["용도"],
                "현재판매량(MJ)": ["연간판매량", "판매량계"],
                "최소경제성만족판매량(MJ)": ["최소경제성만족판매량"],
                "달성률": ["달성률"],
                "적용마진(원/MJ)": ["적용마진"]
            }
            
            final_df = pd.DataFrame()
            for label, keywords in view_cols_map.items():
                found = find_col(result_df, keywords)
                if found:
                    final_df[label] = result_df[found]
            
            try:
                styler = final_df.style
                if "최소경제성만족판매량(MJ)" in final_df.columns:
                    styler = styler.background_gradient(subset=["최소경제성만족판매량(MJ)"], cmap="Oranges")
                
                format_dict = {
                    "현재판매량(MJ)": "{:,.0f}",
                    "최소경제성만족판매량(MJ)": "{:,.1f}",
                    "달성률": "{:.1f}%",
                    "적용마진(원/MJ)": "{:.4f}"
                }
                valid_format = {k: v for k, v in format_dict.items() if k in final_df.columns}
                styler = styler.format(valid_format)

                st.dataframe(styler, use_container_width=True, hide_index=True)
            except:
                st.dataframe(final_df, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                result_df.to_excel(writer, index=False)
                writer.sheets['Sheet1'].set_column('A:Z', 18)
            st.download_button("📥 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "primary")

            st.divider()
            st.subheader("🧮 개별 프로젝트 산출 근거")
            
            name_col = find_col(result_df, ["투자분석명", "공사명"])
            if name_col:
                selected = st.selectbox("프로젝트 선택:", result_df[name_col].unique())
                row = result_df[result_df[name_col] == selected].iloc[0]
                
                col_inv = find_col(result_df, ["배관투자"])
                col_cont = find_col(result_df, ["분담금"])
                col_vol = find_col(result_df, ["판매량계", "연간판매량"])
                col_prof = find_col(result_df, ["판매수익"])
                col_len = find_col(result_df, ["길이"])
                col_hh = find_col(result_df, ["계획전수"])
                col_use = find_col(result_df, ["용도"])

                inv = parse_value(row.get(col_inv))
                cont = parse_value(row.get(col_cont))
                vol = parse_value(row.get(col_vol))
                profit = parse_value(row.get(col_prof))
                length = parse_value(row.get(col_len))
                hh = parse_value(row.get(col_hh))
                usage = str(row.get(col_use, ""))

                pvifa = (1 - (1 + target_irr) ** (-period_input)) / target_irr
                net_inv = inv - cont
                req_capital = max(0, net_inv / pvifa)
                
                maint_c = length * cost_maint_m_input
                if any(k in usage for k in ['공동', '단독', '주택', '아파트']):
                    admin_c = hh * cost_admin_hh_input
                    note = "주택용"
                else:
                    admin_c = length * cost_admin_m_input
                    note = "비주택"
                total_sga = maint_c + admin_c
                
                dep = inv / period_input
                req_ebit = (req_capital - dep) / (1 - tax_rate)
                req_gross = req_ebit + total_sga + dep
                
                auto_margin = profit / vol if vol > 0 else 0
                if margin_override_input > 0:
                    final_margin = margin_override_input
                else:
                    final_margin = auto_margin

                final_vol = req_gross / final_margin if final_margin > 0 else 0

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**1. 투자 정보**")
                    st.write(f"- 순투자액: **{net_inv:,.0f}** 원")
                    st.write(f"- 운영 비용: {total_sga:,.0f} 원")
                with c2:
                    st.markdown("**2. 수익 구조**")
                    st.info(f"👉 **적용 마진:** {final_margin:.4f} 원/MJ")

                st.markdown("---")
                if final_vol > 0:
                    verify_margin = final_vol * final_margin
                    verify_ocf = (verify_margin - total_sga - dep) * (1 - tax_rate) + dep
                    verify_npv = (verify_ocf * pvifa) - net_inv
                    
                    st.write(f"**[최종 결과]** 목표 달성 최소 판매량: **{final_vol:,.1f} MJ**")
                    if abs(verify_npv) < 1000:
                        st.success("✅ NPV ≈ 0 검증 완료")
                    else:
                        st.warning("⚠️ 미세 오차 발생")

            col_id = find_col(result_df, ["공사관리번호", "관리번호"])
            chart_data_ready = False
            chart_df = pd.DataFrame()

            if col_id:
                chart_df = result_df.copy()
                chart_df['년도'] = chart_df[col_id].astype(str).str[:4]
                chart_df = chart_df[chart_df['년도'].str.isnumeric()]
                chart_df['년도'] = chart_df['년도'].astype(int)
                chart_df = chart_df[(chart_df['년도'] >= 2020) & (chart_df['년도'] <= 2024)]
                if not chart_df.empty:
                    chart_data_ready = True

            if chart_data_ready:
                st.divider()
                st.header("📉 경제성 분석 리포트")
                
                st.subheader("1. 연도별 최소 판매량 추이 (Annual)")
                tab1, tab2 = st.tabs(["📊 전체 추이 (막대)", "📈 용도별 상세 (선형)"])
                
                with tab1:
                    total_by_year = chart_df.groupby('년도')['최소경제성만족판매량'].sum()
                    st.bar_chart(total_by_year, color="#FF6C6C")
                    display_df = pd.DataFrame(total_by_year).reset_index()
                    display_df.columns = ['Year', 'Total Volume (MJ)']
                    st.dataframe(display_df.style.format({"Total Volume (MJ)": "{:,.0f}"}), hide_index=True)
                    csv = display_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 데이터 다운로드 (CSV)", csv, "annual_total.csv", "text/csv")
                
                with tab2:
                    col_use = find_col(chart_df, ["용도", "구분"])
                    if col_use:
                        usage_list = sorted(chart_df[col_use].unique().tolist())
                        usage_list.insert(0, "전체 합계 (Total)")
                        selected_usage = st.selectbox("분석할 용도 선택:", usage_list, key="annual_usage")
                        
                        full_idx = range(2020, 2025)
                        if selected_usage == "전체 합계 (Total)":
                            usage_by_year = chart_df.groupby('년도')['최소경제성만족판매량'].sum()
                            chart_color = "#FF4B4B"
                        else:
                            filtered_df = chart_df[chart_df[col_use] == selected_usage]
                            usage_by_year = filtered_df.groupby('년도')['최소경제성만족판매량'].sum()
                            chart_color = "#FFA500"
                        usage_by_year = usage_by_year.reindex(full_idx, fill_value=0)
                        
                        st.line_chart(usage_by_year, color=chart_color)
                        display_df = pd.DataFrame(usage_by_year).reset_index()
                        display_df.columns = ['Year', 'Volume (MJ)']
                        st.dataframe(display_df.style.format({"Volume (MJ)": "{:,.0f}"}), hide_index=True)
                        csv_usg = display_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(f"📥 {selected_usage} 데이터 다운로드", csv_usg, f"annual_{selected_usage}.csv", "text/csv")
                    else:
                        st.warning("용도 컬럼 없음")

                st.divider()
                st.subheader("2. 연도별 누적 최소 판매량 (Cumulative)")
                tab_cum1, tab_cum2 = st.tabs(["📊 전체 누적 (막대)", "📈 용도별 누적 (선형)"])
                
                with tab_cum1:
                    annual_sum = chart_df.groupby('년도')['최소경제성만족판매량'].sum().sort_index()
                    full_idx = range(2020, 2025)
                    annual_sum = annual_sum.reindex(full_idx, fill_value=0)
                    cumulative_sum = annual_sum.cumsum()
                    st.bar_chart(cumulative_sum, color="#4CAF50")
                    cum_df = pd.DataFrame({"연도": cumulative_sum.index, "누적 판매량 (MJ)": cumulative_sum.values})
                    st.dataframe(cum_df.style.format({"누적 판매량 (MJ)": "{:,.0f}"}), hide_index=True)
                    csv_cum = cum_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 누적 데이터 다운로드 (CSV)", csv_cum, "cumulative_total.csv", "text/csv")
                
                with tab_cum2:
                    col_use = find_col(chart_df, ["용도", "구분"])
                    if col_use:
                        usage_list_cum = sorted(chart_df[col_use].unique().tolist())
                        usage_list_cum.insert(0, "전체 합계 (Total)")
                        selected_usage_cum = st.selectbox("누적 분석할 용도 선택:", usage_list_cum, key="cum_usage")
                        
                        if selected_usage_cum == "전체 합계 (Total)":
                            annual_data = chart_df.groupby('년도')['최소경제성만족판매량'].sum()
                            chart_color_cum = "#2E7D32" 
                        else:
                            filtered_df_cum = chart_df[chart_df[col_use] == selected_usage_cum]
                            annual_data = filtered_df_cum.groupby('년도')['최소경제성만족판매량'].sum()
                            chart_color_cum = "#009688"
                        annual_data = annual_data.reindex(full_idx, fill_value=0)
                        cumulative_data = annual_data.cumsum()
                        st.line_chart(cumulative_data, color=chart_color_cum)
                        cum_disp_df = pd.DataFrame(cumulative_data).reset_index()
                        cum_disp_df.columns = ['Year', 'Cumulative Volume (MJ)']
                        st.dataframe(cum_disp_df.style.format({"Cumulative Volume (MJ)": "{:,.0f}"}), hide_index=True)
                        csv_cum_usg = cum_disp_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(f"📥 {selected_usage_cum} 누적 데이터 다운로드", csv_cum_usg, f"cumulative_{selected_usage_cum}.csv", "text/csv")
            
            elif not chart_data_ready:
                st.divider()
                st.info("⚠️ 2020~2024년 데이터가 없어 그래프를 그릴 수 없습니다.")

# --------------------------------------------------------------------------
# [화면 2] 신규배관 경제성 분석 Simulation (신규)
# --------------------------------------------------------------------------
elif page_mode == "신규배관 경제성 분석 Simulation":
    
    with st.sidebar:
        st.subheader("⚙️ 시뮬레이션 기준")
        sim_discount_rate = st.number_input("할인율 (Target IRR, %)", value=6.15, format="%.2f", step=0.01)
        sim_tax_rate = st.number_input("법인세율 (%)", value=20.9, format="%.1f", step=0.1)
        sim_period = st.number_input("사업 기간 (년)", value=30, step=1)
        
        st.subheader("💰 비용 단가 (2024년 기준)")
        sim_cost_maint = st.number_input("배관 유지비 (원/m)", value=8222)
        
        st.markdown("**일반관리비 단가 (두 가지)**")
        # [주의] 여기서 정의한 변수명이 simulate_project 호출부와 일치해야 에러가 안 납니다.
        sim_cost_admin_jeon = st.number_input("일반관리비 (원/전)", value=6209)
        sim_cost_admin_m = st.number_input("일반관리비 (원/m)", value=13605)

    st.title("🏗️ 신규배관 경제성 분석 Simulation")
    st.markdown("💡 **신규 투자 건에 대해 NPV, IRR, 회수기간을 시뮬레이션합니다.**")
    st.warning("🚨 **[중요]** 본 시뮬레이션은 형님의 요청대로 **3가지 판관비(배관유지비+일반m당+일반전당)를 모두 합산**하여 계산합니다.")
    
    st.divider()
    
    # 입력 폼 (2단 레이아웃)
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. 투자 정보")
        sim_len = st.number_input("투자 길이 (m)", value=7000.0, step=10.0, format="%.1f")
        sim_inv = st.number_input("투자 금액 (원)", value=7000000000, step=1000000)
        sim_contrib = st.number_input("시설 분담금 (계, 원)", value=7000000000, step=500000)
        
        st.markdown("---")
        st.subheader("2. 시설 특성")
        sim_jeon = st.number_input("공급 전수 (전)", value=2, step=1)
        st.caption("※ '전'은 계량기 개수입니다.")

    with col2:
        st.subheader("3. 수익 정보")
        sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0, step=10000.0)
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037, step=100000)
        sim_cost = st.number_input("연간 판매원가 (매입비, 원)", value=256160477, step=100000)
        sim_other = st.number_input("기타 이익 (원)", value=0, step=10000)
        
    st.divider()
    
    if st.button("🚀 경제성 분석 실행 (Run Analysis)", type="primary"):
        # 계산
        # 여기서 사이드바의 변수명(sim_cost_admin_jeon 등)을 정확히 전달합니다.
        res = simulate_project(
            sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost,
            sim_jeon, sim_discount_rate/100, sim_tax_rate/100, sim_period,
            sim_cost_maint, sim_cost_admin_jeon, sim_cost_admin_m
        )
        
        # 결과
        st.subheader("📊 시뮬레이션 결과 (핵심 지표)")
        m1, m2, m3 = st.columns(3)
        
        m1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
                  delta="투자 적격" if res['npv']>0 else "투자 부적격", 
                  delta_color="normal" if res['npv']>0 else "inverse")
        
        irr_val = res['irr'] * 100
        m2.metric("2. 내부수익률 (IRR)", f"{irr_val:.2f} %", 
                  delta=f"목표 {sim_discount_rate}% 대비", 
                  delta_color="normal" if irr_val >= sim_discount_rate else "inverse")
        
        dpp_display = f"{res['dpp']:.1f} 년" if res['dpp'] < 999 else "회수 불가 (30년 초과)"
        m3.metric("3. 할인회수기간 (DPP)", dpp_display,
                  delta="원금 회수 시점", delta_color="off")
        
        # 상세 데이터 (비용 구조 명확화)
        st.error(f"""
        **[비용 합산 상세 (3중 구조 - 무조건 합산)]**
        * **1) 배관 유지비 (m당):** {res['c1']:,.0f} 원 ({sim_len:,.0f}m × {sim_cost_maint:,.0f}원)
        * **2) 일반관리비 (m당):** {res['c2']:,.0f} 원 ({sim_len:,.0f}m × {sim_cost_admin_m:,.0f}원)
        * **3) 일반관리비 (전당):** {res['c3']:,.0f} 원 ({sim_jeon}전 × {sim_cost_admin_jeon:,.0f}원)
        --------------------------------------------------
        * **👉 연간 총 판관비:** **{res['sga']:,.0f} 원** (매년 고정 지출)
        """)
        
        # 차트
        st.subheader("📈 30년 현금흐름")
        cf_df = pd.DataFrame({"연차": range(31), "현금흐름": res['flows'], "누적 현금흐름": np.cumsum(res['flows'])})
        
        t1, t2 = st.tabs(["연도별 흐름", "누적 흐름"])
        with t1: 
            st.bar_chart(cf_df.set_index("연차")["현금흐름"])
            st.caption("* 0년차: 투자비 지출(음수) / 1~30년차: 영업이익 회수(양수)")
        with t2: 
            st.line_chart(cf_df.set_index("연차")["누적 현금흐름"])
            st.caption("* 누적 그래프가 0을 넘어서는 시점이 원금 회수 시점입니다.")
        
        csv_sim = cf_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 결과 다운로드 (CSV)", csv_sim, "simulation_result.csv", "text/csv")
