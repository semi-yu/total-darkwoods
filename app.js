(() => {
  "use strict";

  const state = {
    db: null,
    selectedCategory: "ALL",
    selectedClass: "ALL",
    selectedStation: "ALL",
    selectedCrafting: "ALL",
    searchQuery: "",
    showDynamicCols: true,
    sortKey: "itemId",
    sortOrder: "asc",
    selectedItemId: null,
    itemMap: new Map(),
  };

  // DOM Elements
  const els = {
    projectTitle: document.getElementById("projectTitle"),
    sourcePathLabel: document.getElementById("sourcePathLabel"),
    schemaVersionBadge: document.getElementById("schemaVersionBadge"),
    classCountLabel: document.getElementById("classCountLabel"),
    categoryTabs: document.getElementById("categoryTabs"),
    searchInput: document.getElementById("searchInput"),
    btnClearSearch: document.getElementById("btnClearSearch"),
    classFilter: document.getElementById("classFilter"),
    stationFilter: document.getElementById("stationFilter"),
    craftingFilter: document.getElementById("craftingFilter"),
    toggleDynamicCols: document.getElementById("toggleDynamicCols"),
    btnResetFilters: document.getElementById("btnResetFilters"),
    visibleCount: document.getElementById("visibleCount"),
    totalCount: document.getElementById("totalCount"),
    activeFilterChips: document.getElementById("activeFilterChips"),
    loadNotice: document.getElementById("loadNotice"),
    loadNoticeText: document.getElementById("loadNoticeText"),
    workspaceGrid: document.getElementById("workspaceGrid"),
    tableHead: document.getElementById("tableHead"),
    tableBody: document.getElementById("tableBody"),
    emptyState: document.getElementById("emptyState"),
    detailPanel: document.getElementById("detailPanel"),
    detailBadges: document.getElementById("detailBadges"),
    detailTitle: document.getElementById("detailTitle"),
    detailAssetName: document.getElementById("detailAssetName"),
    detailBody: document.getElementById("detailBody"),
    btnCloseDetail: document.getElementById("btnCloseDetail"),
    fileInput: document.getElementById("fileInput"),
    fileInputFallback: document.getElementById("fileInputFallback"),
    btnSchemaModal: document.getElementById("btnSchemaModal"),
    schemaModal: document.getElementById("schemaModal"),
    schemaModalBody: document.getElementById("schemaModalBody"),
    btnCloseSchemaModal: document.getElementById("btnCloseSchemaModal"),
  };

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatAttributeValue(val, attrObj, fieldName) {
    if (val === null || val === undefined) return "-";
    // 한국어 보조 라벨(<fieldName>Ko)이 있으면 함께 표시
    const koKey = `${fieldName}Ko`;
    if (attrObj && attrObj[koKey] && typeof val === "string") {
      return `${attrObj[koKey]} (${val})`;
    }
    if (typeof val === "boolean") return val ? "Yes" : "No";
    if (typeof val === "number") return Number.isInteger(val) ? String(val) : String(Number(val.toFixed(3)));
    if (typeof val === "object") {
      if ("x" in val && "y" in val && "z" in val) return `(${val.x}, ${val.y}, ${val.z})`;
      if ("x" in val && "y" in val) return `${val.x} × ${val.y}`;
      if ("displayName" in val && "itemId" in val) return `${val.displayName} (#${val.itemId})`;
      if ("spriteName" in val) return val.spriteName || val.assetName || "Sprite";
      return JSON.stringify(val);
    }
    return String(val);
  }

  // 현재 필터 상태에서 표시할 동적 속성(attributes) 필드 스키마 계산
  function getActiveDynamicFields() {
    if (!state.db || !state.showDynamicCols) return [];
    const classSchemas = state.db.classSchemas || {};

    let targetClasses = [];
    if (state.selectedClass !== "ALL") {
      targetClasses = [state.selectedClass];
    } else if (state.selectedCategory !== "ALL") {
      const cat = (state.db.categories || []).find((c) => c.itemType === state.selectedCategory);
      if (cat && Array.isArray(cat.scriptClasses)) {
        targetClasses = cat.scriptClasses;
      }
    }

    if (targetClasses.length === 0) return [];

    const seen = new Set();
    const fields = [];
    for (const clsName of targetClasses) {
      const schema = classSchemas[clsName];
      if (!schema || !Array.isArray(schema.fields)) continue;
      for (const f of schema.fields) {
        if (f.isBaseField || seen.has(f.name)) continue;
        seen.add(f.name);
        fields.push(f);
      }
    }
    return fields;
  }

  // 데이터베이스 초기화 (하드코딩 없이 JSON 메타데이터만으로 UI 구성)
  function initializeDatabase(db) {
    state.db = db;
    state.itemMap.clear();
    for (const item of db.items || []) {
      state.itemMap.set(item.itemId, item);
    }

    els.loadNotice.hidden = true;
    els.projectTitle.textContent = db.project || "Total Darkwoods";
    els.sourcePathLabel.textContent = db.sourcePath || "";
    els.schemaVersionBadge.textContent = `Schema v${db.schemaVersion || "1.1.0"}`;
    els.totalCount.textContent = String(db.totalCount ?? (db.items || []).length);

    const classNames = Object.keys(db.classSchemas || {});
    els.classCountLabel.textContent = String(classNames.length);

    buildDynamicCategoryTabs();
    buildDynamicSelectFilters();
    renderSchemaModal();
    renderAll();
  }

  // 동적 대분류 탭 생성 (db.categories 기반)
  function buildDynamicCategoryTabs() {
    const db = state.db;
    const total = (db.items || []).length;
    const categories = Array.isArray(db.categories) ? db.categories : [];

    const tabsHtml = [
      `<button type="button" class="cat-tab ${state.selectedCategory === "ALL" ? "active" : ""}" data-category="ALL">
        <span>전체</span>
        <span class="cat-count">${total}</span>
      </button>`,
    ];

    for (const cat of categories) {
      const isActive = state.selectedCategory === cat.itemType ? "active" : "";
      tabsHtml.push(
        `<button type="button" class="cat-tab ${isActive}" data-category="${escapeHtml(cat.itemType)}" title="C# 클래스: ${escapeHtml((cat.scriptClasses || []).join(", "))}">
          <span>${escapeHtml(cat.itemTypeKo || cat.itemType)}</span>
          <span class="cat-count">${cat.count}</span>
        </button>`
      );
    }

    els.categoryTabs.innerHTML = tabsHtml.join("");
  }

  // C# 클래스 및 제작 스테이션 필터 옵션을 JSON 데이터로부터 동적 구축
  function buildDynamicSelectFilters() {
    const db = state.db;
    const byScriptClass = (db.summary && db.summary.byScriptClass) || {};
    const classSchemas = db.classSchemas || {};
    const allClassNames = Array.from(
      new Set([...Object.keys(byScriptClass), ...Object.keys(classSchemas)])
    ).sort();

    els.classFilter.innerHTML = [
      `<option value="ALL">전체 클래스 (${allClassNames.length})</option>`,
      ...allClassNames.map((cls) => {
        const cnt = byScriptClass[cls] ?? 0;
        return `<option value="${escapeHtml(cls)}">${escapeHtml(cls)} (${cnt})</option>`;
      }),
    ].join("");

    // 제작 스테이션 목록도 레시피/Enum에서 동적 수집
    const stationMap = new Map();
    for (const item of db.items || []) {
      const craftedBy = (item.crafting && item.crafting.craftedBy) || [];
      for (const r of craftedBy) {
        if (r.stationType) {
          stationMap.set(r.stationType, r.stationTypeKo || r.stationType);
        }
      }
    }

    els.stationFilter.innerHTML = [
      `<option value="ALL">전체 스테이션</option>`,
      ...Array.from(stationMap.entries()).map(
        ([st, stKo]) => `<option value="${escapeHtml(st)}">${escapeHtml(stKo)} (${escapeHtml(st)})</option>`
      ),
    ].join("");
  }

  function getFilteredAndSortedItems() {
    if (!state.db || !Array.isArray(state.db.items)) return [];

    const q = state.searchQuery.trim().toLowerCase();

    const filtered = state.db.items.filter((item) => {
      if (state.selectedCategory !== "ALL" && item.itemType !== state.selectedCategory) {
        return false;
      }
      if (state.selectedClass !== "ALL" && item.scriptClass !== state.selectedClass) {
        return false;
      }
      const craftedBy = (item.crafting && item.crafting.craftedBy) || [];
      const usedIn = (item.crafting && item.crafting.usedIn) || [];

      if (state.selectedStation !== "ALL") {
        const matchesStation = craftedBy.some((r) => r.stationType === state.selectedStation);
        if (!matchesStation) return false;
      }

      if (state.selectedCrafting === "CRAFTABLE" && craftedBy.length === 0) return false;
      if (state.selectedCrafting === "INGREDIENT" && usedIn.length === 0) return false;
      if (state.selectedCrafting === "STANDALONE" && (craftedBy.length > 0 || usedIn.length > 0)) return false;

      if (q) {
        const haystacks = [
          String(item.itemId),
          item.displayName,
          item.assetName,
          item.itemType,
          item.itemTypeKo,
          item.scriptClass,
          item.equipmentCategoryKo,
          item.description,
          item.statsSummary,
          JSON.stringify(item.attributes || {}),
          ...craftedBy.flatMap((r) => [
            r.recipeName,
            r.stationTypeKo,
            ...(r.ingredients || []).map((ing) => ing.displayName),
          ]),
        ];
        const joined = haystacks.filter(Boolean).join(" ").toLowerCase();
        if (!joined.includes(q)) return false;
      }

      return true;
    });

    const dir = state.sortOrder === "asc" ? 1 : -1;
    const key = state.sortKey;

    filtered.sort((a, b) => {
      let va;
      let vb;

      if (key.startsWith("attr:")) {
        const attrKey = key.slice(5);
        va = a.attributes ? a.attributes[attrKey] : undefined;
        vb = b.attributes ? b.attributes[attrKey] : undefined;
      } else if (key === "craftedByCount") {
        va = ((a.crafting && a.crafting.craftedBy) || []).length;
        vb = ((b.crafting && b.crafting.craftedBy) || []).length;
      } else if (key === "usedInCount") {
        va = ((a.crafting && a.crafting.usedIn) || []).length;
        vb = ((b.crafting && b.crafting.usedIn) || []).length;
      } else {
        va = a[key];
        vb = b[key];
      }

      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;

      if (typeof va === "number" && typeof vb === "number") {
        return (va - vb) * dir;
      }
      if (typeof va === "boolean" && typeof vb === "boolean") {
        return (Number(va) - Number(vb)) * dir;
      }
      return String(va).localeCompare(String(vb), "ko") * dir;
    });

    return filtered;
  }

  function renderTableHeader(dynamicFields) {
    const baseCols = [
      { key: "itemId", label: "ID" },
      { key: "displayName", label: "아이템명 / 에셋" },
      { key: "itemTypeKo", label: "대분류" },
      { key: "scriptClass", label: "C# 클래스" },
      { key: "maxStack", label: "스택" },
      { key: "statsSummary", label: "핵심 수치 요약" },
      { key: "craftedByCount", label: "제작법" },
      { key: "usedInCount", label: "재료 사용처" },
    ];

    const renderTh = (colKey, label, isDynamic = false, tooltip = null) => {
      const isSorted = state.sortKey === colKey;
      const arrow = isSorted ? (state.sortOrder === "asc" ? "▲" : "▼") : "";
      const cls = ["sortable", isDynamic ? "dynamic-col-header" : ""].filter(Boolean).join(" ");
      const titleAttr = tooltip ? `title="${escapeHtml(tooltip)}"` : "";
      return `<th class="${cls}" data-sort="${escapeHtml(colKey)}" ${titleAttr}>
        ${escapeHtml(label)}<span class="sort-indicator">${arrow}</span>
      </th>`;
    };

    const ths = baseCols.map((c) => renderTh(c.key, c.label));
    for (const f of dynamicFields) {
      const tip = [f.csharpType, f.header ? `[${f.header}]` : null, f.tooltip].filter(Boolean).join(" · ");
      ths.push(renderTh(`attr:${f.name}`, f.name, true, tip));
    }
    if (dynamicFields.length === 0) {
      ths.push(`<th>설명</th>`);
    }

    els.tableHead.innerHTML = `<tr>${ths.join("")}</tr>`;
  }

  function renderTableBody(items, dynamicFields) {
    els.visibleCount.textContent = String(items.length);
    els.emptyState.hidden = items.length > 0;

    const rowsHtml = items.map((item) => {
      const isSelected = state.selectedItemId === item.itemId ? "selected" : "";
      const craftedBy = (item.crafting && item.crafting.craftedBy) || [];
      const usedIn = (item.crafting && item.crafting.usedIn) || [];

      const craftedSummary =
        craftedBy.length > 0
          ? `<span class="badge" title="${escapeHtml(craftedBy.map((r) => `${r.recipeName} (${r.stationTypeKo})`).join(", "))}">${craftedBy.length}종 (${escapeHtml(craftedBy[0].stationTypeKo)})</span>`
          : `<span style="color:var(--text-muted)">-</span>`;

      const usedInSummary =
        usedIn.length > 0
          ? `<span class="badge">${usedIn.length}개 레시피</span>`
          : `<span style="color:var(--text-muted)">-</span>`;

      const dynamicCells = dynamicFields.map((f) => {
        const rawVal = item.attributes ? item.attributes[f.name] : undefined;
        return `<td class="dynamic-col-cell">${escapeHtml(formatAttributeValue(rawVal, item.attributes, f.name))}</td>`;
      });

      const descCell =
        dynamicFields.length === 0
          ? `<td class="desc-cell">${escapeHtml(item.description || "-")}</td>`
          : "";

      return `<tr data-item-id="${item.itemId}" class="${isSelected}">
        <td class="col-id">#${item.itemId}</td>
        <td>
          <div class="item-name-cell">
            <span class="item-display-name">${escapeHtml(item.displayName)}</span>
            <span class="item-asset-sub">${escapeHtml(item.assetName)}</span>
          </div>
        </td>
        <td>
          <span class="badge">${escapeHtml(item.itemTypeKo || item.itemType)}</span>
        </td>
        <td>
          <span class="badge badge-class">${escapeHtml(item.scriptClass)}</span>
        </td>
        <td style="font-family:var(--font-mono)">${item.maxStack}</td>
        <td><div class="stats-pre">${escapeHtml(item.statsSummary || "-")}</div></td>
        <td>${craftedSummary}</td>
        <td>${usedInSummary}</td>
        ${dynamicCells.join("")}
        ${descCell}
      </tr>`;
    });

    els.tableBody.innerHTML = rowsHtml.join("");
  }

  function renderActiveFilterChips() {
    const chips = [];
    if (state.selectedCategory !== "ALL") {
      chips.push(`대분류: ${state.selectedCategory}`);
    }
    if (state.selectedClass !== "ALL") {
      chips.push(`클래스: ${state.selectedClass}`);
    }
    if (state.selectedStation !== "ALL") {
      chips.push(`스테이션: ${state.selectedStation}`);
    }
    if (state.selectedCrafting !== "ALL") {
      chips.push(`조합: ${state.selectedCrafting}`);
    }
    if (state.searchQuery.trim()) {
      chips.push(`검색: "${state.searchQuery.trim()}"`);
    }
    els.activeFilterChips.innerHTML = chips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("");
  }

  function renderDetailPanel(itemId) {
    const item = state.itemMap.get(itemId);
    if (!item) {
      els.detailPanel.hidden = true;
      els.workspaceGrid.classList.remove("with-detail");
      return;
    }

    els.detailPanel.hidden = false;
    els.workspaceGrid.classList.add("with-detail");

    const badges = [
      `<span class="badge">#${item.itemId}</span>`,
      `<span class="badge">${escapeHtml(item.itemTypeKo)} (${escapeHtml(item.itemType)})</span>`,
      `<span class="badge badge-class">${escapeHtml(item.scriptClass)}</span>`,
    ];
    if (item.equipmentCategoryKo || item.equipmentCategory) {
      badges.push(
        `<span class="badge">슬롯: ${escapeHtml(item.equipmentCategoryKo || item.equipmentCategory)}</span>`
      );
    }
    els.detailBadges.innerHTML = badges.join("");
    els.detailTitle.textContent = item.displayName;
    els.detailAssetName.textContent = `${item.assetName} (${item.assetGuid})`;

    const sections = [];

    // 1. 기본 정보
    sections.push(`
      <div class="detail-section">
        <div class="detail-section-title">기본 정보 (ItemData)</div>
        <p style="margin-bottom:8px;color:var(--text-primary)">${escapeHtml(item.description || "설명 없음")}</p>
        ${
          item.statsSummary
            ? `<pre style="background:var(--bg-surface);padding:8px;border-radius:6px;font-size:12px;color:var(--accent);margin-bottom:8px;white-space:pre-wrap">${escapeHtml(item.statsSummary)}</pre>`
            : ""
        }
        <div class="kv-grid">
          <span class="kv-key">Max Stack</span><span class="kv-val">${item.maxStack}</span>
          <span class="kv-key">Asset Path</span><span class="kv-val">${escapeHtml(item.assetPath)}</span>
          <span class="kv-key">Icon Sprite</span><span class="kv-val">${escapeHtml(item.icon ? `${item.icon.spriteName} (${item.icon.texturePath})` : "-")}</span>
        </div>
      </div>
    `);

    // 2. 클래스별 동적 속성 (classSchemas 메타데이터와 결합)
    const classSchema = (state.db.classSchemas || {})[item.scriptClass];
    const attrs = item.attributes || {};
    const attrKeys = Object.keys(attrs).filter((k) => !k.endsWith("Ko"));

    if (attrKeys.length > 0) {
      const fieldMetaMap = new Map();
      if (classSchema && Array.isArray(classSchema.fields)) {
        for (const f of classSchema.fields) {
          fieldMetaMap.set(f.name, f);
        }
      }

      const kvRows = attrKeys.map((k) => {
        const meta = fieldMetaMap.get(k);
        const typeLabel = meta ? ` (${meta.csharpType})` : "";
        const tooltip = meta && meta.tooltip ? `title="${escapeHtml(meta.tooltip)}"` : "";
        return `<span class="kv-key" ${tooltip}>${escapeHtml(k)}${escapeHtml(typeLabel)}</span>
                <span class="kv-val">${escapeHtml(formatAttributeValue(attrs[k], attrs, k))}</span>`;
      });

      sections.push(`
        <div class="detail-section">
          <div class="detail-section-title">
            <span>동적 클래스 속성 (${escapeHtml(item.scriptClass)})</span>
            <span>${attrKeys.length}개 필드</span>
          </div>
          <div class="kv-grid">${kvRows.join("")}</div>
        </div>
      `);
    }

    // 3. 조합법 (Crafted By & Used In)
    const craftedBy = (item.crafting && item.crafting.craftedBy) || [];
    const usedIn = (item.crafting && item.crafting.usedIn) || [];

    const craftedHtml =
      craftedBy.length > 0
        ? craftedBy
            .map(
              (r) => `
          <div class="recipe-card">
            <div class="recipe-header">
              <span>${escapeHtml(r.recipeName)} (×${r.resultAmount})</span>
              <span class="badge">${escapeHtml(r.stationTypeKo)}</span>
            </div>
            <div class="ingredient-list">
              ${(r.ingredients || [])
                .map(
                  (ing) =>
                    `<button type="button" class="item-link-chip" data-jump-item="${ing.itemId}">
                      ${escapeHtml(ing.displayName)} ×${ing.amount}
                    </button>`
                )
                .join("")}
            </div>
          </div>`
            )
            .join("")
        : `<p style="color:var(--text-muted);font-size:12px">이 아이템을 제작하는 레시피가 없습니다.</p>`;

    const usedInHtml =
      usedIn.length > 0
        ? `<div class="ingredient-list" style="margin-top:6px">
            ${usedIn
              .map(
                (u) =>
                  `<button type="button" class="item-link-chip" data-jump-item="${u.resultItemId}" title="${escapeHtml(u.recipeName)} (${escapeHtml(u.stationTypeKo)})">
                    → ${escapeHtml(u.resultDisplayName)} (필요: ${u.requiredAmount})
                  </button>`
              )
              .join("")}
          </div>`
        : `<p style="color:var(--text-muted);font-size:12px">다른 아이템의 제작 재료로 사용되지 않습니다.</p>`;

    sections.push(`
      <div class="detail-section">
        <div class="detail-section-title">제작 레시피 (Crafted By: ${craftedBy.length})</div>
        ${craftedHtml}
      </div>
      <div class="detail-section">
        <div class="detail-section-title">재료 사용처 (Used In: ${usedIn.length})</div>
        ${usedInHtml}
      </div>
    `);

    els.detailBody.innerHTML = sections.join("");
  }

  function renderSchemaModal() {
    if (!state.db) return;
    const classSchemas = state.db.classSchemas || {};
    const enumSchemas = state.db.enumSchemas || {};

    const classCards = Object.values(classSchemas).map((cls) => {
      const fieldsHtml = (cls.fields || [])
        .map(
          (f) =>
            `<tr>
              <td style="font-family:var(--font-mono);color:var(--accent)">${escapeHtml(f.name)}</td>
              <td style="font-family:var(--font-mono)">${escapeHtml(f.csharpType)}${f.isEnum ? " (enum)" : ""}</td>
              <td style="font-family:var(--font-mono)">${escapeHtml(JSON.stringify(f.defaultValue))}</td>
              <td>${escapeHtml(f.header || "-")}</td>
              <td>${escapeHtml(f.tooltip || "-")}</td>
            </tr>`
        )
        .join("");

      return `
        <div class="detail-section">
          <div class="detail-section-title">
            <span>${escapeHtml(cls.className)} : ${escapeHtml((cls.baseClasses || []).join(", "))}</span>
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-secondary)">${escapeHtml(cls.scriptPath)}</span>
          </div>
          <table class="item-table" style="font-size:12px">
            <thead>
              <tr><th>필드명</th><th>C# 타입</th><th>기본값</th><th>Header</th><th>Tooltip</th></tr>
            </thead>
            <tbody>${fieldsHtml}</tbody>
          </table>
        </div>
      `;
    });

    const enumCards = Object.entries(enumSchemas).map(([enumName, entries]) => {
      const chips = entries
        .map((e) => `<span class="badge">${e.value}: ${escapeHtml(e.name)}${e.labelKo ? ` (${escapeHtml(e.labelKo)})` : ""}</span>`)
        .join(" ");
      return `<div style="margin-bottom:8px"><strong>${escapeHtml(enumName)}</strong>: ${chips}</div>`;
    });

    els.schemaModalBody.innerHTML = `
      <h3 style="font-size:15px">1. 동적 발견된 C# ItemData 클래스 (${classCards.length}종)</h3>
      ${classCards.join("")}
      <h3 style="font-size:15px;margin-top:12px">2. 동적 발견된 C# Enum (${enumCards.length}종)</h3>
      <div class="detail-section">${enumCards.join("")}</div>
    `;
  }

  function renderAll() {
    if (!state.db) return;
    const dynamicFields = getActiveDynamicFields();
    const items = getFilteredAndSortedItems();
    renderTableHeader(dynamicFields);
    renderTableBody(items, dynamicFields);
    renderActiveFilterChips();
    renderDetailPanel(state.selectedItemId);
  }

  // Event Listeners
  els.categoryTabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".cat-tab");
    if (!btn) return;
    state.selectedCategory = btn.dataset.category;
    buildDynamicCategoryTabs();
    renderAll();
  });

  els.searchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    els.btnClearSearch.hidden = !state.searchQuery;
    renderAll();
  });

  els.btnClearSearch.addEventListener("click", () => {
    state.searchQuery = "";
    els.searchInput.value = "";
    els.btnClearSearch.hidden = true;
    renderAll();
  });

  els.classFilter.addEventListener("change", (e) => {
    state.selectedClass = e.target.value;
    renderAll();
  });

  els.stationFilter.addEventListener("change", (e) => {
    state.selectedStation = e.target.value;
    renderAll();
  });

  els.craftingFilter.addEventListener("change", (e) => {
    state.selectedCrafting = e.target.value;
    renderAll();
  });

  els.toggleDynamicCols.addEventListener("change", (e) => {
    state.showDynamicCols = e.target.checked;
    renderAll();
  });

  els.btnResetFilters.addEventListener("click", () => {
    state.selectedCategory = "ALL";
    state.selectedClass = "ALL";
    state.selectedStation = "ALL";
    state.selectedCrafting = "ALL";
    state.searchQuery = "";
    els.searchInput.value = "";
    els.btnClearSearch.hidden = true;
    els.classFilter.value = "ALL";
    els.stationFilter.value = "ALL";
    els.craftingFilter.value = "ALL";
    buildDynamicCategoryTabs();
    renderAll();
  });

  els.tableHead.addEventListener("click", (e) => {
    const th = e.target.closest("th.sortable");
    if (!th) return;
    const key = th.dataset.sort;
    if (state.sortKey === key) {
      state.sortOrder = state.sortOrder === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortOrder = "asc";
    }
    renderAll();
  });

  els.tableBody.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-item-id]");
    if (!tr) return;
    const itemId = Number(tr.dataset.itemId);
    state.selectedItemId = state.selectedItemId === itemId ? null : itemId;
    renderAll();
  });

  els.detailBody.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-jump-item]");
    if (!btn) return;
    const targetId = Number(btn.dataset.jumpItem);
    if (state.itemMap.has(targetId)) {
      state.selectedItemId = targetId;
      renderAll();
    }
  });

  els.btnCloseDetail.addEventListener("click", () => {
    state.selectedItemId = null;
    renderAll();
  });

  els.btnSchemaModal.addEventListener("click", () => {
    els.schemaModal.hidden = false;
  });

  els.btnCloseSchemaModal.addEventListener("click", () => {
    els.schemaModal.hidden = true;
  });

  els.schemaModal.addEventListener("click", (e) => {
    if (e.target === els.schemaModal) {
      els.schemaModal.hidden = true;
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== els.searchInput) {
      e.preventDefault();
      els.searchInput.focus();
    } else if (e.key === "Escape") {
      if (!els.schemaModal.hidden) {
        els.schemaModal.hidden = true;
      } else if (state.selectedItemId !== null) {
        state.selectedItemId = null;
        renderAll();
      }
    }
  });

  function handleFileUpload(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(String(ev.target.result));
        initializeDatabase(parsed);
      } catch (err) {
        alert(`JSON 파싱 오류: ${err.message}`);
      }
    };
    reader.readAsText(file, "utf-8");
  }

  els.fileInput.addEventListener("change", (e) => handleFileUpload(e.target.files[0]));
  els.fileInputFallback.addEventListener("change", (e) => handleFileUpload(e.target.files[0]));

  // 초기 items.json 자동 fetch
  async function bootstrap() {
    try {
      const res = await fetch("./items.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      initializeDatabase(data);
    } catch (err) {
      els.loadNotice.hidden = false;
    }
  }

  bootstrap();
})();
