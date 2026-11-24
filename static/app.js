document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE] 메인 3탭 페이지 로드 완료");

  // ==================== 0. 전역 작업 잠금 & 범용 진행 바 ====================
  let isAppBusy = false;
  const globalProgressBox = document.getElementById("global-progress-box");
  const progressText = document.getElementById("progress-text");
  const progressPercent = document.getElementById("progress-percent");
  const progressFill = document.getElementById("progress-fill");

  function setAppBusy(busy) {
    isAppBusy = busy;
    const selectors = [
      ".tab-btn",
      "#tab1-load-btn",
      "#tab1-mode-select",
      ".tab1-quick-btn",
      "#tab1-chat-btn",
      "#tab2-submit",
      "#tab3-load-btn",
      "#tab3-chat-btn",
      "#tab4-search-btn",
      ".preset-chip",
      ".action-btn-sm",
    ];
    selectors.forEach((sel) => {
      document.querySelectorAll(sel).forEach((el) => {
        el.disabled = busy;
      });
    });
  }

  function showProgress(percent, text) {
    if (!globalProgressBox) return;
    progressText.textContent = text;
    progressPercent.textContent = `${percent}%`;
    progressFill.style.width = `${percent}%`;
    globalProgressBox.classList.remove("hidden");
  }

  function hideProgress() {
    if (!globalProgressBox) return;
    setTimeout(() => {
      if (!isAppBusy) {
        globalProgressBox.classList.add("hidden");
        progressFill.style.width = "0%";
      }
    }, 450);
  }

  // ==================== 1. 탭 전환 로직 ====================
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");
  let tab4Initialized = false;

  function switchTab(targetTab) {
    console.log(`[TAB] 탭 전환 (tab=${targetTab})`);
    tabBtns.forEach((b) => b.classList.toggle("active", b.getAttribute("data-tab") === targetTab));
    tabPanels.forEach((panel) => {
      if (panel.id === `tab-${targetTab}`) {
        panel.classList.remove("hidden");
        panel.classList.add("active");
      } else {
        panel.classList.add("hidden");
        panel.classList.remove("active");
      }
    });

    if (targetTab === "4" && !tab4Initialized) {
      tab4Initialized = true;
      loadScreener();
    }
  }

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (isAppBusy) return;
      switchTab(btn.getAttribute("data-tab"));
    });
  });

  // ==================== 2. 탭 1: 종목 조회 → 자동 분석 → 후속 채팅 ====================
  const tab1LoadForm = document.getElementById("tab1-load-form");
  const tab1CodeInput = document.getElementById("tab1-code");
  const tab1ModeSelect = document.getElementById("tab1-mode-select");
  const tab1LoadBtn = document.getElementById("tab1-load-btn");
  const tab1Error = document.getElementById("tab1-error");
  const tab1Loading = document.getElementById("tab1-loading");
  const tab1EvidencePanel = document.getElementById("tab1-evidence-panel");
  const tab1ChatSection = document.getElementById("tab1-chat-section");
  const tab1ReportBox = document.getElementById("tab1-report-box");
  const tab1ChatLog = document.getElementById("tab1-chat-log");
  const tab1ChatForm = document.getElementById("tab1-chat-form");
  const tab1QuestionInput = document.getElementById("tab1-question");
  const tab1ChatBtn = document.getElementById("tab1-chat-btn");

  let tab1CurrentCode = "";
  let tab1ConversationId = "";
  let tab1EvidenceData = null;
  let tab1CurrentMode = tab1ModeSelect ? tab1ModeSelect.value : "expert";
  let tab1Reports = { expert: null, beginner: null };

  // 상단 조회 폼 옆 셀렉트 박스 변경 시 즉시 리포트 전환/생성
  if (tab1ModeSelect) {
    tab1ModeSelect.addEventListener("change", async () => {
      if (isAppBusy) return;
      const targetMode = tab1ModeSelect.value;
      tab1CurrentMode = targetMode;
      if (tab1Reports[targetMode]) {
        renderReportMarkdown(tab1Reports[targetMode]);
      } else if (tab1EvidenceData) {
        setAppBusy(true);
        showProgress(65, "선택하신 모드로 AI 리포트를 생성하고 있습니다...");
        try {
          await fetchAndRenderReport(tab1CurrentCode, targetMode, tab1EvidenceData);
          showProgress(100, "리포트 전환 완료!");
        } finally {
          setAppBusy(false);
          hideProgress();
        }
      }
    });
  }

  // 빠른 선택 예시 버튼
  document.querySelectorAll(".tab1-quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (isAppBusy) return;
      const code = btn.getAttribute("data-code");
      tab1CodeInput.value = code;
      runInitialAnalysis(code);
    });
  });

  // 1단계: 종목 조회 & 자동 전문가 분석 시작
  tab1LoadForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (isAppBusy) return;
    const code = tab1CodeInput.value.trim();
    if (code) runInitialAnalysis(code);
  });

  async function runInitialAnalysis(code) {
    if (isAppBusy) return;
    console.log(`[ANALYZE] 탭1 심층분석 요청 시작 (code=${code})`);

    tab1ConversationId = "";
    tab1EvidenceData = null;
    tab1CurrentCode = code;
    tab1Reports = { expert: null, beginner: null };
    if (tab1ModeSelect) tab1CurrentMode = tab1ModeSelect.value;

    tab1Error.classList.add("hidden");
    tab1Error.textContent = "";
    tab1EvidencePanel.classList.add("hidden");
    tab1ChatSection.classList.add("hidden");
    tab1ReportBox.innerHTML = "";
    tab1ChatLog.innerHTML = "";
    tab1Loading.classList.add("hidden");

    setAppBusy(true);
    showProgress(30, "1/2 단계: 시세 · 공시 · 뉴스 · 기술지표 데이터를 수집 중입니다...");

    try {
      // 1단계: /fetch 로 네이버·DART·FDR·Serper 근거 데이터 먼저 수집 (Vercel 10초 타임아웃 방어)
      const fetchResp = await fetch("/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const evData = await safeParseJson(fetchResp);
      if (!evData || !evData.name) {
        const errMsg = (evData && evData.errors && evData.errors[0]) || `데이터 수집에 실패했습니다 (상태 코드: ${fetchResp.status}).`;
        console.error("[ERROR] 탭1 수집 오류:", errMsg);
        tab1Error.textContent = `⚠️ ${errMsg}`;
        tab1Error.classList.remove("hidden");
        return;
      }

      tab1EvidenceData = evData;
      renderTab1Evidence(evData);
      tab1EvidencePanel.classList.remove("hidden");
      tab1ChatSection.classList.remove("hidden");

      // 2단계: 현재 선택된 모드(전문가용 / 초보자용)로 리포트 생성
      showProgress(70, "2/2 단계: 수집 완료! AI가 심층 분석 리포트를 작성 중입니다...");
      await fetchAndRenderReport(code, tab1CurrentMode, evData);
      showProgress(100, "분석이 완료되었습니다!");
    } catch (err) {
      console.error("[ERROR] 탭1 통신 오류:", err.message);
      tab1Error.textContent = "⚠️ 서버와 통신하는 중 오류가 발생했습니다.";
      tab1Error.classList.remove("hidden");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  }

  async function fetchAndRenderReport(code, mode, evData) {
    const modeLabel = mode === "beginner" ? "초보자용 쉬운 해설" : "전문가용 상세 리포트";
    tab1ReportBox.innerHTML = `<p style="color:#6b7280;">수집된 데이터를 바탕으로 <strong>${modeLabel}</strong>를 작성 중입니다...</p>`;

    try {
      const analyzeResp = await fetch("/api/chat/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          mode,
          is_initial: true,
          evidence: evData,
        }),
      });

      const data = await safeParseJson(analyzeResp);
      if (!data) {
        const fallbackErr = `AI 서버 응답을 해석할 수 없습니다 (상태 코드: ${analyzeResp.status}).`;
        console.error("[ERROR] 탭1 AI 분석 오류:", fallbackErr);
        tab1ReportBox.innerHTML = `<p style="color:#b91c1c;">⚠️ ${escapeHtml(fallbackErr)}</p>`;
        return;
      }

      if (data.error) {
        console.error("[ERROR] 탭1 AI 분석 오류:", data.error);
        tab1Error.textContent = `⚠️ ${data.error}`;
        tab1Error.classList.remove("hidden");
        if (!data.answer) {
          tab1ReportBox.innerHTML = `<p style="color:#b91c1c;">안내: ${escapeHtml(data.error)}</p>`;
          return;
        }
      }

      if (data.conversation_id && !tab1ConversationId) {
        tab1ConversationId = data.conversation_id;
      }

      const answerText = data.answer || "응답을 받지 못했습니다.";
      tab1Reports[mode] = answerText;
      renderReportMarkdown(answerText);
    } catch (err) {
      console.error("[ERROR] 탭1 리포트 통신 오류:", err.message);
      tab1ReportBox.innerHTML = `<p style="color:#b91c1c;">⚠️ 리포트를 불러오는 중 오류가 발생했습니다.</p>`;
    }
  }

  function renderReportMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      tab1ReportBox.innerHTML = DOMPurify.sanitize(marked.parse(String(text || "")));
    } else {
      tab1ReportBox.textContent = text;
    }
  }

  // 2단계: 수집된 근거를 유지한 채 후속 채팅 이어가기
  tab1ChatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isAppBusy) return;
    const question = tab1QuestionInput.value.trim();
    if (!question || !tab1CurrentCode) return;

    appendChatMessage(tab1ChatLog, question, "user");
    tab1QuestionInput.value = "";
    setAppBusy(true);
    showProgress(55, "수집된 근거를 바탕으로 AI가 답변을 작성 중입니다...");

    const loadingBubble = appendChatMessage(tab1ChatLog, "수집된 근거와 대화 맥락을 바탕으로 답변 생성 중...", "bot");

    try {
      const resp = await fetch("/api/chat/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: tab1CurrentCode,
          question,
          is_initial: false,
          conversation_id: tab1ConversationId,
          evidence: tab1EvidenceData,
        }),
      });

      const data = await safeParseJson(resp);
      loadingBubble.remove();

      if (!data || data.error) {
        const errMsg = (data && data.error) || `응답 오류 (상태 코드: ${resp.status})`;
        console.error("[ERROR] 탭1 후속 채팅 오류:", errMsg);
        appendChatMessage(tab1ChatLog, `안내: ${errMsg}`, "bot");
        return;
      }

      if (data.conversation_id) {
        tab1ConversationId = data.conversation_id;
      }

      appendChatMessage(tab1ChatLog, data.answer || "응답을 받지 못했습니다.", "bot");
      showProgress(100, "답변 완료!");
    } catch (err) {
      loadingBubble.remove();
      console.error("[ERROR] 탭1 후속 통신 오류:", err.message);
      appendChatMessage(tab1ChatLog, "⚠️ 서버와 통신하는 중 오류가 발생했습니다.", "bot");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  });

  function renderTab1Evidence(ev) {
    document.getElementById("tab1-stock-name").textContent = ev.name || "-";
    document.getElementById("tab1-stock-code-badge").textContent = ev.code || "-";

    // 오늘의 거시 시장 환경 (코스피, 코스닥, 원/달러)
    const marketBar = document.getElementById("tab1-market-bar");
    const mc = ev.market_context || {};
    const mcItems = [];
    ["kospi", "kosdaq", "usd_krw"].forEach((k) => {
      if (mc[k]) {
        const sign = mc[k].change_rate > 0 ? "+" : "";
        const color = mc[k].change_rate > 0 ? "#dc2626" : mc[k].change_rate < 0 ? "#2563eb" : "#374151";
        mcItems.push(
          `<span class="ind-badge">${escapeHtml(mc[k].label)} ${mc[k].value.toLocaleString("ko-KR")} <span style="color:${color}">(${sign}${mc[k].change_rate}%)</span></span>`
        );
      }
    });
    marketBar.innerHTML = mcItems.join("");

    const snap = ev.snapshot || {};
    const currency = ev.currency || "KRW";
    document.getElementById("tab1-val-price").textContent = formatPrice(snap.current_price, currency);

    const changeEl = document.getElementById("tab1-val-change");
    changeEl.classList.remove("up", "down");
    if (snap.change_rate != null) {
      const sign = snap.change_rate > 0 ? "+" : "";
      changeEl.textContent = `${sign}${snap.change_rate}%`;
      if (snap.change_rate > 0) changeEl.classList.add("up");
      else if (snap.change_rate < 0) changeEl.classList.add("down");
    } else {
      changeEl.textContent = "-";
    }

    document.getElementById("tab1-val-cap").textContent =
      snap.market_cap_text ? snap.market_cap_text : formatKoreanCurrency(snap.market_cap);

    const labelPer = document.getElementById("tab1-label-per");
    const labelPbr = document.getElementById("tab1-label-pbr");
    const valPer = document.getElementById("tab1-val-per");
    const valPbr = document.getElementById("tab1-val-pbr");
    const financialsBox = document.getElementById("tab1-financials-box");
    const etfBox = document.getElementById("tab1-etf-box");
    const overviewBox = document.getElementById("tab1-overview-box");

    if (ev.asset_type === "etf" && ev.etf_info) {
      const etf = ev.etf_info;
      labelPer.textContent = "NAV (괴리율)";
      valPer.textContent = etf.nav != null
        ? (etf.deviation_rate != null ? `${formatPrice(etf.nav, currency)} (${etf.deviation_rate}%)` : formatPrice(etf.nav, currency))
        : "-";
      labelPbr.textContent = "펀드보수 / 분배금";
      valPbr.textContent = `${etf.total_fee ?? "-"}% / ${etf.dividend_yield ?? "-"}%`;

      financialsBox.classList.add("hidden");
      etfBox.classList.remove("hidden");

      const badges = [
        `기초지수: ${etf.base_index || "-"}`,
        `운용사: ${etf.issuer || "-"}`,
        `1개월: ${etf.return_1m != null ? etf.return_1m + "%" : "-"}`,
        `3개월: ${etf.return_3m != null ? etf.return_3m + "%" : "-"}`,
        `6개월: ${etf.return_6m != null ? etf.return_6m + "%" : "-"}`,
        `1년: ${etf.return_1y != null ? etf.return_1y + "%" : "-"}`,
      ];
      document.getElementById("tab1-etf-returns").innerHTML = badges
        .map((b) => `<span class="ind-badge">${escapeHtml(b)}</span>`)
        .join("");
      document.getElementById("tab1-etf-desc").textContent = etf.description || "상품 설명이 없습니다.";
    } else {
      labelPer.textContent = "PER";
      valPer.textContent = snap.per != null ? `${snap.per}배` : "-";
      labelPbr.textContent = "PBR";
      valPbr.textContent = snap.pbr != null ? `${snap.pbr}배` : "-";

      etfBox.classList.add("hidden");
      if ((ev.financials || []).length > 0) {
        financialsBox.classList.remove("hidden");
      } else {
        financialsBox.classList.add("hidden");
      }
    }

    if (ev.overview) {
      const profileStrip = document.getElementById("tab1-profile-strip");
      const prof = ev.company_profile;
      if (prof && profileStrip) {
        const pItems = [];
        if (prof.ceo) pItems.push(`CEO ${prof.ceo}`);
        if (prof.employees) pItems.push(`임직원 ${Number(prof.employees).toLocaleString("ko-KR")}명`);
        if (prof.city) pItems.push(`본사 ${prof.city}`);
        profileStrip.innerHTML = pItems.map((t) => `<span class="ind-badge">${escapeHtml(t)}</span>`).join("");
      } else if (profileStrip) {
        profileStrip.innerHTML = "";
      }
      document.getElementById("tab1-overview-text").textContent = ev.overview;
      overviewBox.classList.remove("hidden");
    } else {
      overviewBox.classList.add("hidden");
    }

    // 미국 주식용: 월가 컨센서스 & 52주 최고/최저/배당
    const consensusBox = document.getElementById("tab1-consensus-box");
    const consensusStrip = document.getElementById("tab1-consensus-strip");
    if (consensusBox && consensusStrip) {
      const cItems = [];
      const cons = ev.consensus;
      const uh = ev.us_highlights;
      if (cons && cons.target_mean != null) {
        cItems.push(`평균 목표가 ${formatPrice(cons.target_mean, "USD")} (최고 ${formatPrice(cons.target_high, "USD")} / 최저 ${formatPrice(cons.target_low, "USD")})`);
        if (cons.recomm_mean != null) cItems.push(`투자의견 ${cons.recomm_mean} / 5.0`);
      }
      if (uh) {
        if (uh.high_52w != null && uh.low_52w != null) {
          cItems.push(`52주 최고 ${formatPrice(uh.high_52w, "USD")} / 최저 ${formatPrice(uh.low_52w, "USD")}`);
        }
        if (uh.dividend_yield != null) {
          cItems.push(`배당수익률 ${uh.dividend_yield}%${uh.dividend != null ? ` ($${uh.dividend})` : ""}`);
        }
      }
      if (cItems.length > 0) {
        consensusStrip.innerHTML = cItems.map((t) => `<span class="ind-badge">${escapeHtml(t)}</span>`).join("");
        consensusBox.classList.remove("hidden");
      } else {
        consensusStrip.innerHTML = "";
        consensusBox.classList.add("hidden");
      }
    }

    // 기술지표 핵심 요약 (RSI, 볼린저 위치 %, 20일선 이격)
    const techSummaryEl = document.getElementById("tab1-tech-summary");
    const ts = ev.tech_summary;
    if (ts) {
      const gapSign = ts.ma20_gap_pct > 0 ? "+" : "";
      const tsItems = [
        `RSI(14) ${ts.rsi14 ?? "-"}`,
        `볼린저밴드 위치 ${ts.bb_position_pct != null ? ts.bb_position_pct + "%" : "-"}`,
        `20일선 이격도 ${ts.ma20_gap_pct != null ? gapSign + ts.ma20_gap_pct + "%" : "-"}`,
      ];
      techSummaryEl.innerHTML = tsItems.map((t) => `<span class="ind-badge">${escapeHtml(t)}</span>`).join("");
    } else {
      techSummaryEl.innerHTML = "";
    }

    // 동일업종 경쟁사 비교
    const peersBox = document.getElementById("tab1-peers-box");
    const peersList = document.getElementById("tab1-peers-list");
    const peers = ev.peers || [];
    if (peers.length > 0) {
      peersList.innerHTML = peers
        .map((p) => {
          const sign = p.change_rate > 0 ? "+" : "";
          const color = p.change_rate > 0 ? "#dc2626" : p.change_rate < 0 ? "#2563eb" : "#374151";
          const priceStr = formatPrice(p.price, p.currency || currency);
          const rateStr = p.change_rate != null ? `${sign}${p.change_rate}%` : "-";
          return `<span class="ind-badge">${escapeHtml(p.name)} ${priceStr} <span style="color:${color}">(${rateStr})</span></span>`;
        })
        .join("");
      peersBox.classList.remove("hidden");
    } else {
      peersBox.classList.add("hidden");
      peersList.innerHTML = "";
    }

    // 연간 실적 테이블 (한국/미국 공용)
    const tbody = document.getElementById("tab1-finance-tbody");
    const finHeaderLast = document.querySelector("#tab1-financials-box th:last-child");
    if (finHeaderLast) {
      finHeaderLast.textContent = currency === "USD" ? "PER (배)" : "ROE (%)";
    }
    tbody.innerHTML = "";
    const financials = ev.financials || [];
    if (financials.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.style.textAlign = "center";
      td.textContent = "수집된 실적 데이터가 없습니다.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      financials.forEach((row) => {
        const tr = document.createElement("tr");

        const tdPeriod = document.createElement("td");
        tdPeriod.textContent = row.period || "-";

        const tdType = document.createElement("td");
        const badge = document.createElement("span");
        if (row.is_consensus) {
          badge.className = "badge-consensus";
          badge.textContent = "추정(E)";
        } else {
          badge.className = "badge-confirmed";
          badge.textContent = "확정";
        }
        tdType.appendChild(badge);

        const fmtAmount = currency === "USD" ? formatUsdCurrency : formatKoreanCurrency;
        const tdRev = document.createElement("td");
        tdRev.textContent = fmtAmount(row.revenue);

        const tdOp = document.createElement("td");
        tdOp.textContent = fmtAmount(row.operating_income);

        const tdLast = document.createElement("td");
        if (currency === "USD") {
          tdLast.textContent = row.per != null ? `${row.per}배` : "-";
        } else {
          tdLast.textContent = row.roe != null ? `${row.roe}%` : "-";
        }

        tr.append(tdPeriod, tdType, tdRev, tdOp, tdLast);
        tbody.appendChild(tr);
      });
    }

    // 주식용: DART 최신 확정 분기 실적 및 재무상태
    const dartFinBox = document.getElementById("tab1-dart-fin-box");
    const dartFinTitle = document.getElementById("tab1-dart-fin-title");
    const dartFinBadges = document.getElementById("tab1-dart-fin-badges");
    const df = ev.dart_latest_financials;
    if (ev.asset_type !== "etf" && df) {
      dartFinTitle.textContent = `최근 확정 실적 및 재무상태 (${df.period_label || "-"})`;
      const dfItems = [
        `당기 매출: ${formatKoreanCurrency(df.revenue_q)}`,
        `누적 매출: ${formatKoreanCurrency(df.revenue_cum)}`,
        `당기 영업이익: ${formatKoreanCurrency(df.operating_income_q)}`,
        `누적 영업이익: ${formatKoreanCurrency(df.operating_income_cum)}`,
        `당기 순이익: ${formatKoreanCurrency(df.net_income_q)}`,
        `자산총계: ${formatKoreanCurrency(df.total_assets)}`,
        `부채총계: ${formatKoreanCurrency(df.total_liabilities)}`,
        `자본총계: ${formatKoreanCurrency(df.total_equity)}`,
      ];
      dartFinBadges.innerHTML = dfItems.map((t) => `<span class="ind-badge">${escapeHtml(t)}</span>`).join("");
      dartFinBox.classList.remove("hidden");
    } else {
      dartFinBox.classList.add("hidden");
      dartFinBadges.innerHTML = "";
    }

    // 공통: 최근 5일 투자자별 매매동향 (수급) — 데이터 없을 시(미국 등) 숨김
    const trendBox = document.getElementById("tab1-trend-box");
    const trendTbody = document.getElementById("tab1-trend-tbody");
    trendTbody.innerHTML = "";
    const trends = ev.investor_trend || [];
    if (trends.length === 0) {
      trendBox.classList.add("hidden");
    } else {
      trendBox.classList.remove("hidden");
      trends.forEach((t) => {
        const tr = document.createElement("tr");
        const fmtNet = (qty, eok) => {
          if (qty == null) return "-";
          const sign = qty > 0 ? "+" : "";
          const qtyStr = `${sign}${qty.toLocaleString("ko-KR")}`;
          if (eok == null) return qtyStr;
          const eokSign = eok > 0 ? "+" : "";
          return `${qtyStr} (${eokSign}${eok.toLocaleString("ko-KR")}억)`;
        };
        const tdDate = document.createElement("td");
        tdDate.textContent = t.date || "-";
        const tdHold = document.createElement("td");
        tdHold.textContent = t.foreigner_ratio != null ? `${t.foreigner_ratio}%` : "-";
        const tdFor = document.createElement("td");
        tdFor.textContent = fmtNet(t.foreigner_net, t.foreigner_eok);
        tdFor.style.color = t.foreigner_net > 0 ? "#dc2626" : t.foreigner_net < 0 ? "#2563eb" : "";
        const tdOrg = document.createElement("td");
        tdOrg.textContent = fmtNet(t.organ_net, t.organ_eok);
        tdOrg.style.color = t.organ_net > 0 ? "#dc2626" : t.organ_net < 0 ? "#2563eb" : "";
        const tdInd = document.createElement("td");
        tdInd.textContent = fmtNet(t.individual_net, t.individual_eok);
        tdInd.style.color = t.individual_net > 0 ? "#dc2626" : t.individual_net < 0 ? "#2563eb" : "";

        tr.append(tdDate, tdHold, tdFor, tdOrg, tdInd);
        trendTbody.appendChild(tr);
      });
    }

    // 주식용: 최근 3개월 OpenDART 주요 전자공시
    const dartBox = document.getElementById("tab1-dart-box");
    const dartTbody = document.getElementById("tab1-dart-tbody");
    dartTbody.innerHTML = "";
    const disclosures = ev.disclosures || [];
    if (ev.asset_type !== "etf" && disclosures.length > 0) {
      disclosures.forEach((d) => {
        const tr = document.createElement("tr");

        const tdDate = document.createElement("td");
        tdDate.textContent = d.date || "-";

        const tdCat = document.createElement("td");
        const badge = document.createElement("span");
        badge.className = `badge-dart badge-dart-${d.badge_type || "default"}`;
        badge.textContent = d.category || "공시";
        tdCat.appendChild(badge);

        const tdTitle = document.createElement("td");
        tdTitle.style.textAlign = "left";
        const a = document.createElement("a");
        a.href = d.url || "#";
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.style.color = "#1d4ed8";
        a.style.textDecoration = "none";
        a.style.fontWeight = "500";
        a.textContent = `${d.title || "공시 원문"} ↗`;
        tdTitle.appendChild(a);

        tr.append(tdDate, tdCat, tdTitle);
        dartTbody.appendChild(tr);
      });
      dartBox.classList.remove("hidden");
    } else {
      dartBox.classList.add("hidden");
    }

    // 뉴스 카드 리스트
    const newsListEl = document.getElementById("tab1-news-list");
    newsListEl.innerHTML = "";
    const news = ev.news || [];
    if (news.length === 0) {
      const li = document.createElement("li");
      li.className = "news-item";
      li.textContent = "수집된 관련 뉴스가 없습니다.";
      newsListEl.appendChild(li);
    } else {
      news.forEach((item) => {
        const li = document.createElement("li");
        li.className = "news-item";

        const a = document.createElement("a");
        a.className = "news-title";
        a.href = item.url || "#";
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = item.title || "제목 없음";

        const dateDiv = document.createElement("div");
        dateDiv.className = "news-date";
        dateDiv.textContent = item.published || "";

        const descDiv = document.createElement("div");
        descDiv.className = "news-desc";
        descDiv.textContent = item.description || "";

        li.append(a, dateDiv, descDiv);
        newsListEl.appendChild(li);
      });
    }
  }

  // ==================== 3. 탭 2: 리밸런싱 도우미 (Dify 없음) ====================
  const tab2Form = document.getElementById("tab2-form");
  const tab2CodesInput = document.getElementById("tab2-codes");
  const tab2SubmitBtn = document.getElementById("tab2-submit");
  const tab2Error = document.getElementById("tab2-error");
  const tab2Loading = document.getElementById("tab2-loading");
  const tab2Result = document.getElementById("tab2-result");

  let rebalancePieChart = null;
  let rebalanceFrontierChart = null;

  tab2Form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isAppBusy) return;
    const codes = tab2CodesInput.value.trim();
    if (!codes) return;

    console.log(`[REBALANCE] 탭2 리밸런싱 계산 요청 (codes=${codes})`);
    tab2Error.classList.add("hidden");
    tab2Result.classList.add("hidden");
    tab2Loading.classList.add("hidden");

    setAppBusy(true);
    showProgress(45, "최근 1년 주가 수집 및 3,000회 몬테카를로 시뮬레이션 계산 중...");

    try {
      const resp = await fetch("/api/rebalance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codes }),
      });

      const data = await safeParseJson(resp);
      if (!resp.ok || !data || data.error) {
        const errMsg = (data && data.error) || "리밸런싱 계산에 실패했습니다.";
        console.error("[ERROR] 탭2 계산 오류:", errMsg);
        tab2Error.textContent = `⚠️ ${errMsg}`;
        tab2Error.classList.remove("hidden");
        return;
      }

      renderRebalanceResult(data);
      showProgress(100, "리밸런싱 계산 완료!");
    } catch (err) {
      console.error("[ERROR] 탭2 통신 오류:", err.message);
      tab2Error.textContent = "⚠️ 서버와 통신하는 중 오류가 발생했습니다.";
      tab2Error.classList.remove("hidden");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  });

  function renderRebalanceResult(data) {
    const m = data.metrics || {};
    document.getElementById("reb-return").textContent = m.expected_return != null ? `${m.expected_return}%` : "-";
    document.getElementById("reb-vol").textContent = m.volatility != null ? `${m.volatility}%` : "-";
    document.getElementById("reb-sharpe").textContent = m.sharpe_ratio != null ? `${m.sharpe_ratio}` : "-";

    const weights = data.optimal_weights || {};
    const names = data.names || {};
    const labels = Object.keys(weights);
    const values = Object.values(weights);
    const palette = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

    if (rebalancePieChart) rebalancePieChart.destroy();
    const pieCtx = document.getElementById("rebalance-pie-chart").getContext("2d");
    rebalancePieChart = new Chart(pieCtx, {
      type: "doughnut",
      data: {
        labels: labels.map((code, i) => `${names[code] || code} (${code}) - ${values[i]}%`),
        datasets: [
          {
            data: values,
            backgroundColor: labels.map((_, i) => palette[i % palette.length]),
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom" } },
      },
    });

    if (rebalanceFrontierChart) rebalanceFrontierChart.destroy();
    const frontierCtx = document.getElementById("rebalance-frontier-chart").getContext("2d");
    const simPoints = (data.frontier_points || []).map((p) => ({ x: p.risk, y: p.return }));

    rebalanceFrontierChart = new Chart(frontierCtx, {
      type: "scatter",
      data: {
        datasets: [
          {
            label: "시뮬레이션 조합",
            data: simPoints,
            backgroundColor: "rgba(59, 130, 246, 0.35)",
            pointRadius: 3,
          },
          {
            label: "최대 샤프 최적점",
            data: [{ x: m.volatility, y: m.expected_return }],
            backgroundColor: "#dc2626",
            pointRadius: 8,
            pointStyle: "star",
          },
        ],
      },
      options: {
        responsive: true,
        aspectRatio: window.innerWidth <= 768 ? 1.25 : 1.8,
        scales: {
          x: { title: { display: true, text: "연율화 변동성 리스크 (%)" } },
          y: { title: { display: true, text: "연율화 기대수익률 (%)" } },
        },
      },
    });

    tab2Result.classList.remove("hidden");
  }

  // ==================== 4. 탭 3: 기술지표 차트 + 지표해석기 채팅 ====================
  const tab3LoadForm = document.getElementById("tab3-load-form");
  const tab3CodeInput = document.getElementById("tab3-code");
  const tab3LoadBtn = document.getElementById("tab3-load-btn");
  const tab3Error = document.getElementById("tab3-error");
  const tab3Loading = document.getElementById("tab3-loading");
  const tab3Content = document.getElementById("tab3-content");
  const tab3Badges = document.getElementById("tab3-latest-badges");

  const tab3ChatForm = document.getElementById("tab3-chat-form");
  const tab3QuestionInput = document.getElementById("tab3-question");
  const tab3ChatBtn = document.getElementById("tab3-chat-btn");
  const tab3ChatLog = document.getElementById("tab3-chat-log");

  let techPriceChart = null;
  let techRsiChart = null;
  let tab3CurrentCode = "";
  let tab3LatestIndicators = null;
  let tab3ConversationId = "";

  tab3LoadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isAppBusy) return;
    const code = tab3CodeInput.value.trim();
    if (!code) return;

    tab3Error.classList.add("hidden");
    tab3Content.classList.add("hidden");
    tab3Loading.classList.add("hidden");

    setAppBusy(true);
    showProgress(50, "이동평균선 · RSI · MACD · 볼린저밴드 기술지표를 계산 중입니다...");

    try {
      const resp = await fetch("/api/indicators", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const data = await safeParseJson(resp);
      if (!resp.ok || !data || data.error) {
        const errMsg = (data && data.error) || "기술지표를 불러오지 못했습니다.";
        console.error("[ERROR] 탭3 지표 계산 오류:", errMsg);
        tab3Error.textContent = `⚠️ ${errMsg}`;
        tab3Error.classList.remove("hidden");
        return;
      }

      if (code !== tab3CurrentCode) {
        tab3ConversationId = "";
        tab3CurrentCode = code;
      }
      tab3LatestIndicators = data.latest;

      console.log(`[INDICATOR] 탭3 기술지표 계산 완료 (code=${code})`);
      renderTechBadges(data.latest, data.name || code, data.currency || "KRW");
      renderTechCharts(data);
      tab3Content.classList.remove("hidden");
      showProgress(100, "기술지표 차트 계산 완료!");
    } catch (err) {
      console.error("[ERROR] 탭3 통신 오류:", err.message);
      tab3Error.textContent = "⚠️ 서버와 통신하는 중 오류가 발생했습니다.";
      tab3Error.classList.remove("hidden");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  });

  function renderTechBadges(latest, stockName, currency) {
    if (!latest) return;
    const items = [
      `종목: ${stockName || "-"}`,
      `기준일: ${latest.date}`,
      `종가: ${formatPrice(latest.close, currency)}`,
      `MA5: ${formatPrice(latest.ma5, currency)}`,
      `MA20: ${formatPrice(latest.ma20, currency)}`,
      `MA60: ${formatPrice(latest.ma60, currency)}`,
      `RSI(14): ${latest.rsi14 != null ? latest.rsi14 : "-"}`,
      `MACD: ${latest.macd != null ? latest.macd : "-"}`,
      `볼린저 상/하: ${formatPrice(latest.bb_upper, currency)} / ${formatPrice(latest.bb_lower, currency)}`,
    ];
    tab3Badges.innerHTML = items.map((t) => `<span class="ind-badge">${escapeHtml(t)}</span>`).join("");
  }

  function renderTechCharts(data) {
    if (techPriceChart) techPriceChart.destroy();
    const priceCtx = document.getElementById("tech-price-chart").getContext("2d");
    techPriceChart = new Chart(priceCtx, {
      type: "line",
      data: {
        labels: data.dates,
        datasets: [
          { label: "종가", data: data.close, borderColor: "#111827", borderWidth: 2, pointRadius: 0 },
          { label: "MA5", data: data.ma5, borderColor: "#ef4444", borderWidth: 1.5, pointRadius: 0 },
          { label: "MA20", data: data.ma20, borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0 },
          { label: "MA60", data: data.ma60, borderColor: "#10b981", borderWidth: 1.5, pointRadius: 0 },
          { label: "볼린저 상단", data: data.bb_upper, borderColor: "#9ca3af", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
          { label: "볼린저 하단", data: data.bb_lower, borderColor: "#9ca3af", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        aspectRatio: window.innerWidth <= 768 ? 1.2 : 1.8,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" } },
      },
    });

    if (techRsiChart) techRsiChart.destroy();
    const rsiCtx = document.getElementById("tech-rsi-chart").getContext("2d");
    techRsiChart = new Chart(rsiCtx, {
      type: "line",
      data: {
        labels: data.dates,
        datasets: [
          { label: "RSI(14)", data: data.rsi14, borderColor: "#2563eb", borderWidth: 2, pointRadius: 0 },
          { label: "과매수(70)", data: data.dates.map(() => 70), borderColor: "#dc2626", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
          { label: "과매도(30)", data: data.dates.map(() => 30), borderColor: "#16a34a", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        aspectRatio: window.innerWidth <= 768 ? 1.35 : 1.8,
        scales: { y: { min: 0, max: 100 } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  tab3ChatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isAppBusy) return;
    const question = tab3QuestionInput.value.trim();
    if (!question || !tab3CurrentCode || !tab3LatestIndicators) return;

    console.log("[TECH_CHAT] 탭3 기술지표 숫자 주입 채팅 요청");
    appendChatMessage(tab3ChatLog, question, "user");
    tab3QuestionInput.value = "";
    setAppBusy(true);
    showProgress(60, "지표해석기 AI가 기술지표 숫자를 분석 중입니다...");

    const loadingBubble = appendChatMessage(tab3ChatLog, "계산된 지표를 바탕으로 지표해석기 챗봇이 분석 중...", "bot");

    try {
      const resp = await fetch("/api/chat/tech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: tab3CurrentCode,
          question,
          latest: tab3LatestIndicators, // 눈에 안 보이게 최신 지표 숫자 주입
          conversation_id: tab3ConversationId,
        }),
      });

      const data = await safeParseJson(resp);
      loadingBubble.remove();

      if (!data || data.error) {
        const errMsg = (data && data.error) || `응답 오류 (상태 코드: ${resp.status})`;
        console.error("[ERROR] 탭3 채팅 오류:", errMsg);
        appendChatMessage(tab3ChatLog, `안내: ${errMsg}`, "bot");
        return;
      }

      if (data.conversation_id) {
        tab3ConversationId = data.conversation_id;
      }
      appendChatMessage(tab3ChatLog, data.answer || "응답을 받지 못했습니다.", "bot");
      showProgress(100, "지표 해석 완료!");
    } catch (err) {
      loadingBubble.remove();
      console.error("[ERROR] 탭3 채팅 통신 오류:", err.message);
      appendChatMessage(tab3ChatLog, "⚠️ 서버와 통신하는 중 오류가 발생했습니다.", "bot");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  });

  // ==================== 5. 탭 4: 종목 발굴 스크리너 ====================
  const tab4FilterForm = document.getElementById("tab4-filter-form");
  const tab4Market = document.getElementById("tab4-market");
  const tab4Cap = document.getElementById("tab4-cap");
  const tab4Change = document.getElementById("tab4-change");
  const tab4Sector = document.getElementById("tab4-sector");
  const tab4Keyword = document.getElementById("tab4-keyword");
  const tab4Tbody = document.getElementById("tab4-tbody");
  const tab4Error = document.getElementById("tab4-error");
  const tab4TotalCount = document.getElementById("tab4-total-count");
  const presetChips = document.querySelectorAll(".preset-chip");

  let tab4SortBy = "market_cap";
  let tab4SortDir = "desc";
  let tab4MaxPrice = 0;

  if (tab4FilterForm) {
    tab4FilterForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (isAppBusy) return;
      tab4MaxPrice = 0;
      presetChips.forEach((c) => c.classList.remove("active"));
      loadScreener();
    });

    tab4Market.addEventListener("change", () => {
      if (isAppBusy) return;
      tab4Sector.value = "";
      tab4MaxPrice = 0;
      if (tab4Market.value === "US") {
        tab4Cap.disabled = true;
        tab4Change.disabled = true;
        tab4SortBy = "code";
        tab4SortDir = "asc";
      } else {
        tab4Cap.disabled = false;
        tab4Change.disabled = false;
        tab4SortBy = "market_cap";
        tab4SortDir = "desc";
      }
      loadScreener();
    });

    presetChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        if (isAppBusy) return;
        presetChips.forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");

        const preset = chip.getAttribute("data-preset");
        tab4Keyword.value = "";
        tab4Sector.value = "";
        tab4MaxPrice = 0;

        if (preset === "sp500") {
          tab4Market.value = "US";
          tab4Cap.disabled = true;
          tab4Change.disabled = true;
          tab4SortBy = "code";
          tab4SortDir = "asc";
        } else {
          tab4Market.value = "KR";
          tab4Cap.disabled = false;
          tab4Change.disabled = false;
          tab4SortBy = "market_cap";
          tab4SortDir = "desc";
          tab4Cap.value = "0";
          tab4Change.value = "";

          if (preset === "large") {
            tab4Cap.value = "10";
          } else if (preset === "gainers") {
            tab4Cap.value = "1";
            tab4Change.value = "up3";
            tab4SortBy = "change_rate";
          } else if (preset === "losers") {
            tab4Cap.value = "1";
            tab4Change.value = "down3";
            tab4SortBy = "change_rate";
            tab4SortDir = "asc";
          } else if (preset === "under10k") {
            tab4MaxPrice = 10000;
            tab4Cap.value = "0";
          }
        }
        loadScreener();
      });
    });

    document.querySelectorAll(".sortable-th").forEach((th) => {
      th.addEventListener("click", () => {
        if (isAppBusy || tab4Market.value === "US") return;
        const col = th.getAttribute("data-sort");
        if (tab4SortBy === col) {
          tab4SortDir = tab4SortDir === "desc" ? "asc" : "desc";
        } else {
          tab4SortBy = col;
          tab4SortDir = "desc";
        }
        loadScreener();
      });
    });
  }

  async function loadScreener() {
    if (!tab4Tbody) return;
    tab4Error.classList.add("hidden");
    setAppBusy(true);
    showProgress(45, "종목 스크리너 목록을 불러오는 중입니다...");

    const chgVal = tab4Change.value;
    const payload = {
      market: tab4Market.value,
      min_cap_trillion: tab4Cap.value,
      max_price: tab4MaxPrice,
      min_change: chgVal === "up3" ? 3 : null,
      max_change: chgVal === "down3" ? -3 : null,
      sector: tab4Sector.value,
      keyword: tab4Keyword.value.trim(),
      sort_by: tab4SortBy,
      sort_dir: tab4SortDir,
      limit: 50,
    };

    try {
      const resp = await fetch("/api/screener", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await safeParseJson(resp);
      if (!resp.ok || !data || data.error) {
        tab4Error.textContent = (data && data.error) || "스크리너 데이터를 불러오지 못했습니다.";
        tab4Error.classList.remove("hidden");
        return;
      }

      // 섹터 드롭다운 동기화
      const prevSector = tab4Sector.value;
      tab4Sector.innerHTML = `<option value="">${data.market === "US" ? "전체 섹터" : "시장 전체 (KOSPI/KOSDAQ)"}</option>`;
      (data.sectors || []).forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s;
        opt.textContent = s;
        tab4Sector.appendChild(opt);
      });
      if (prevSector && (data.sectors || []).includes(prevSector)) {
        tab4Sector.value = prevSector;
      }

      tab4TotalCount.textContent = `${data.total.toLocaleString("ko-KR")}개 발견`;
      renderScreenerTable(data.items || [], data.market);
      showProgress(100, "조회 완료");
    } catch (err) {
      console.error("[ERROR] 스크리너 오류:", err.message);
      tab4Error.textContent = "서버와 통신하는 중 오류가 발생했습니다.";
      tab4Error.classList.remove("hidden");
    } finally {
      setAppBusy(false);
      hideProgress();
    }
  }

  function renderScreenerTable(items, market) {
    tab4Tbody.innerHTML = "";
    if (items.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 7;
      td.style.textAlign = "center";
      td.textContent = "조건에 맞는 종목이 없습니다.";
      tr.appendChild(td);
      tab4Tbody.appendChild(tr);
      return;
    }

    items.forEach((it) => {
      const tr = document.createElement("tr");

      const tdCode = document.createElement("td");
      tdCode.textContent = it.code;

      const tdName = document.createElement("td");
      tdName.style.textAlign = "left";
      tdName.style.fontWeight = "600";
      tdName.textContent = it.name;

      const tdSub = document.createElement("td");
      tdSub.textContent = it.sub || "-";

      const tdPrice = document.createElement("td");
      tdPrice.textContent = it.price != null ? formatPrice(it.price, market === "US" ? "USD" : "KRW") : "-";

      const tdChg = document.createElement("td");
      if (it.change_rate != null) {
        const sign = it.change_rate > 0 ? "+" : "";
        tdChg.textContent = `${sign}${it.change_rate}%`;
        tdChg.style.color = it.change_rate > 0 ? "#e11d48" : it.change_rate < 0 ? "#2563eb" : "";
        tdChg.style.fontWeight = "600";
      } else {
        tdChg.textContent = "-";
      }

      const tdCap = document.createElement("td");
      tdCap.textContent = it.market_cap != null ? formatKoreanCurrency(it.market_cap) : (it.industry || "-");

      const tdAct = document.createElement("td");
      tdAct.style.textAlign = "center";
      const grp = document.createElement("div");
      grp.className = "action-btn-group";

      const btnAnalyze = document.createElement("button");
      btnAnalyze.type = "button";
      btnAnalyze.className = "action-btn-sm";
      btnAnalyze.textContent = "AI 분석";
      btnAnalyze.addEventListener("click", () => {
        if (isAppBusy) return;
        tab1CodeInput.value = it.code;
        switchTab("1");
        runInitialAnalysis(it.code);
      });

      const btnChart = document.createElement("button");
      btnChart.type = "button";
      btnChart.className = "action-btn-sm";
      btnChart.textContent = "차트";
      btnChart.addEventListener("click", () => {
        if (isAppBusy) return;
        tab3CodeInput.value = it.code;
        switchTab("3");
        tab3LoadForm.dispatchEvent(new Event("submit"));
      });

      grp.append(btnAnalyze, btnChart);
      tdAct.appendChild(grp);

      tr.append(tdCode, tdName, tdSub, tdPrice, tdChg, tdCap, tdAct);
      tab4Tbody.appendChild(tr);
    });
  }

  // ==================== 공통 유틸리티 & 자동완성 ====================
  function setupAutocomplete(inputEl, listEl, onSelect) {
    if (!inputEl || !listEl) return;
    let debounceTimer = null;

    inputEl.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      const q = inputEl.value.trim();
      if (!q) {
        listEl.classList.add("hidden");
        listEl.innerHTML = "";
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
          const data = await resp.json();
          const items = data.items || [];
          listEl.innerHTML = "";
          if (items.length === 0) {
            listEl.classList.add("hidden");
            return;
          }
          items.forEach((it) => {
            const li = document.createElement("li");
            li.className = "autocomplete-item";
            const nationTag = it.nation === "USA" ? "US" : "KR";
            li.innerHTML = `<span class="ac-name">${escapeHtml(it.name)}</span><span class="ac-meta">${nationTag} · ${escapeHtml(it.code)} · ${escapeHtml(it.exchange || "")}</span>`;
            li.addEventListener("mousedown", (e) => {
              e.preventDefault();
              inputEl.value = it.code;
              listEl.classList.add("hidden");
              if (onSelect) onSelect(it.code);
            });
            listEl.appendChild(li);
          });
          listEl.classList.remove("hidden");
        } catch {
          listEl.classList.add("hidden");
        }
      }, 200);
    });

    inputEl.addEventListener("blur", () => {
      setTimeout(() => listEl.classList.add("hidden"), 150);
    });
  }

  setupAutocomplete(
    document.getElementById("tab1-code"),
    document.getElementById("tab1-autocomplete-list"),
    (code) => runInitialAnalysis(code)
  );
  setupAutocomplete(
    document.getElementById("tab3-code"),
    document.getElementById("tab3-autocomplete-list"),
    null
  );

  function formatPrice(val, currency) {
    if (val === null || val === undefined) return "-";
    if (currency === "USD") {
      return `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `${Number(val).toLocaleString("ko-KR")}원`;
  }

  function formatUsdCurrency(amount) {
    if (amount === null || amount === undefined) return "-";
    const isNeg = amount < 0;
    const absVal = Math.abs(amount);
    let str = "";
    if (absVal >= 1_000_000_000_000) {
      str = `$${(absVal / 1_000_000_000_000).toFixed(2)}T`;
    } else if (absVal >= 1_000_000_000) {
      str = `$${(absVal / 1_000_000_000).toFixed(2)}B`;
    } else if (absVal >= 1_000_000) {
      str = `$${(absVal / 1_000_000).toFixed(1)}M`;
    } else {
      str = `$${absVal.toLocaleString("en-US")}`;
    }
    return isNeg ? `-${str}` : str;
  }

  async function safeParseJson(resp) {
    try {
      return await resp.json();
    } catch {
      return null;
    }
  }

  function appendChatMessage(container, text, role) {
    const div = document.createElement("div");
    div.className = `chat-msg ${role}`;
    if (role === "bot" && window.marked && window.DOMPurify) {
      div.classList.add("markdown-body");
      div.innerHTML = DOMPurify.sanitize(marked.parse(String(text || "")));
    } else {
      div.textContent = text;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
  }

  function formatKoreanCurrency(amount) {
    if (amount === null || amount === undefined) return "-";
    const isNegative = amount < 0;
    const absVal = Math.abs(amount);
    const eok = Math.round(absVal / 100_000_000);
    const jo = Math.floor(eok / 10_000);
    const restEok = eok % 10_000;

    let formatted = "";
    if (jo > 0) {
      formatted =
        restEok > 0
          ? `${jo.toLocaleString("ko-KR")}조 ${restEok.toLocaleString("ko-KR")}억`
          : `${jo.toLocaleString("ko-KR")}조`;
    } else {
      formatted = `${eok.toLocaleString("ko-KR")}억`;
    }
    return isNegative ? `-${formatted}` : formatted;
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
});
