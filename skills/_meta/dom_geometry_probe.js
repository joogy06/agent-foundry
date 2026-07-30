/**
 * dom_geometry_probe.js — S073. The single in-page geometry measurement function.
 *
 * ONE implementation, shared by every transport. Exported as a SOURCE STRING so it can
 * run through puppeteer's page.evaluate, a browser-MCP javascript tool, Playwright, or a
 * devtools console without being reimplemented. Two copies of measurement logic would
 * drift, and different hosts would then return different verdicts for the same page.
 *
 * Emits RAW MEASUREMENTS ONLY — never verdicts. Rule evaluation lives in
 * geometry_rules.py, so false-positive tuning is unit-testable against saved JSON
 * without launching a browser, and three different skills can apply different rules to
 * the same measurements.
 *
 * Two modes, both optional and combinable:
 *   measure  — measure declared specs. `cardinality: "many"` returns EVERY match.
 *              Default is "one", which preserves the historical single-match behaviour
 *              of visual_arbiter_measure.mjs.
 *   discover — auto-detect repeated sibling groups and measure their corresponding
 *              descendants. This is what catches "3 line-item prices at the same
 *              coordinate" WITHOUT the project having to declare the relationship in
 *              advance — repetition is discoverable from the DOM, and a project will
 *              never have pre-declared the relation that would have caught its own bug.
 *
 * Deliberately NOT collected: element text, outerHTML, attribute values. The page under
 * review is untrusted and its measurements feed an LLM; shipping page-controlled strings
 * into that path is a prompt-injection surface. Only numbers, a closed set of computed
 * properties, and caller-supplied ids cross the boundary.
 *
 * PROBE_VERSION is recorded in the evidence artifact. Changing measurement semantics
 * REQUIRES bumping it, otherwise two runs are not comparable.
 */

const PROBE_VERSION = "dom-geometry-probe.v1";

/** Closed set. Anything not needed by a rule in geometry_rules.py stays out. */
const DEFAULT_PROPS = [
  "position", "display", "visibility", "opacity", "overflow", "overflow-x", "overflow-y",
  "z-index", "transform", "clip-path",
  "line-height", "font-size",
  "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
  "border-top-color", "border-bottom-color",
  "padding-top", "padding-right", "padding-bottom", "padding-left",
  "margin-top", "margin-bottom",
  "background-color", "color",
];

/**
 * The probe body. Serialised to a string and evaluated in-page; it must therefore be
 * fully self-contained and reference nothing from this module's scope.
 */
function __probeBody(input) {
  const props = input.props || [];
  const round = (n) => Math.round(n * 100) / 100; // keep subpixel, drop float noise

  function rect(node) {
    const r = node.getBoundingClientRect();
    return { x: round(r.x), y: round(r.y), w: round(r.width), h: round(r.height) };
  }

  function computedOf(node) {
    const cs = window.getComputedStyle(node);
    const out = {};
    for (const p of props) out[p] = cs.getPropertyValue(p);
    return out;
  }

  /** Visually hidden by computed properties — never by class name. */
  function hiddenKind(node, cs, r) {
    if (cs.display === "none") return "display-none";
    if (cs.visibility === "hidden" || cs.visibility === "collapse") return "visibility-hidden";
    if (parseFloat(cs.opacity || "1") === 0) return "opacity-zero";
    if (r.w === 0 || r.h === 0) return "zero-size";
    // screen-reader-only signature: tiny + clipped + absolutely positioned
    const clipped = (cs.clipPath && cs.clipPath !== "none") ||
                    (cs.clip && cs.clip !== "auto");
    if (clipped && r.w <= 2 && r.h <= 2) return "sr-only";
    return null;
  }

  /**
   * Nearest ancestor chain that actually clips, innermost first. Containment must be
   * judged against this, not against the immediate parent: a child may sit outside its
   * parent's padding box yet still be clipped (content silently lost) or paint freely
   * outside a bordered panel (visible defect). Those are different findings.
   */
  function clipChain(node) {
    const chain = [];
    let p = node.parentElement;
    while (p) {
      const cs = window.getComputedStyle(p);
      const ox = cs.overflowX, oy = cs.overflowY;
      if ((ox && ox !== "visible") || (oy && oy !== "visible")) {
        chain.push({ bbox: rect(p), overflow_x: ox, overflow_y: oy });
      }
      p = p.parentElement;
    }
    return chain;
  }

  function paddingBox(node) {
    const cs = window.getComputedStyle(node);
    const r = node.getBoundingClientRect();
    const bt = parseFloat(cs.borderTopWidth) || 0;
    const br = parseFloat(cs.borderRightWidth) || 0;
    const bb = parseFloat(cs.borderBottomWidth) || 0;
    const bl = parseFloat(cs.borderLeftWidth) || 0;
    return {
      x: round(r.x + bl), y: round(r.y + bt),
      w: round(r.width - bl - br), h: round(r.height - bt - bb),
    };
  }

  function describe(node, specId, index, selector) {
    const cs = window.getComputedStyle(node);
    const r = rect(node);
    const hk = hiddenKind(node, cs, r);
    return {
      spec_id: specId,
      index: index,
      element_id: index === null ? specId : `${specId}[${index}]`,
      selector: selector,
      kind: hk ? "hidden" : "found",
      hidden_reason: hk,
      bbox: r,
      padding_box: paddingBox(node),
      parent_bbox: node.parentElement ? rect(node.parentElement) : null,
      parent_padding_box: node.parentElement ? paddingBox(node.parentElement) : null,
      clip_chain: clipChain(node),
      // depth lets the evaluator exclude ancestor/descendant pairs without re-walking
      depth: (() => { let d = 0, p = node.parentElement; while (p) { d++; p = p.parentElement; } return d; })(),
      // Whether this node holds its OWN text — a boolean and a length, never the text
      // itself (the page is untrusted and this output reaches an LLM). The clipping rule
      // needs it: without it, every short empty div reports "glyphs are cut off".
      has_direct_text: Array.from(node.childNodes).some(
        (n) => n.nodeType === 3 && (n.nodeValue || "").trim().length > 0
      ),
      direct_text_length: Array.from(node.childNodes)
        .filter((n) => n.nodeType === 3)
        .reduce((acc, n) => acc + (n.nodeValue || "").trim().length, 0),
      computed: computedOf(node),
    };
  }

  const elements = [];
  const errors = [];

  // ---- mode: measure declared specs -------------------------------------------------
  for (const spec of input.specs || []) {
    let nodes;
    try {
      nodes = Array.from(document.querySelectorAll(spec.selector));
    } catch (e) {
      errors.push(`selector '${spec.selector}' invalid: ${e.message}`);
      continue;
    }
    const cardinality = spec.cardinality || "one";
    if (nodes.length === 0) {
      elements.push({
        spec_id: spec.id, index: null, element_id: spec.id, selector: spec.selector,
        kind: "not_found", hidden_reason: null, bbox: null,
      });
      continue;
    }
    if (cardinality === "one") {
      elements.push(describe(nodes[0], spec.id, null, spec.selector));
      if (nodes.length > 1) {
        // Not an error, but the caller asked for one and the page has several. Silence
        // here is how repeated-element defects stayed invisible.
        errors.push(`spec '${spec.id}' matched ${nodes.length} nodes but cardinality is 'one'`);
      }
    } else {
      nodes.forEach((n, i) => elements.push(describe(n, spec.id, i, spec.selector)));
    }
  }

  // ---- mode: discover repeated sibling groups ---------------------------------------
  const groups = [];
  if (input.discover) {
    const minMembers = input.discover.min_members || 2;
    const roots = input.discover.root
      ? Array.from(document.querySelectorAll(input.discover.root))
      : [document.body];

    for (const root of roots) {
      if (!root) continue;
      // ROOT INCLUSION: the root itself must be considered, not only its descendants.
      // `root.querySelectorAll('*')` excludes root — that omission produced a false
      // "clean" verdict on a panel whose own border was the defect.
      const candidates = [root, ...root.querySelectorAll("*")];
      for (const parent of candidates) {
        const kids = Array.from(parent.children);
        if (kids.length < minMembers) continue;
        const bySig = new Map();
        for (const k of kids) {
          const sig = k.tagName + "." + Array.from(k.classList).sort().join(".");
          if (!bySig.has(sig)) bySig.set(sig, []);
          bySig.get(sig).push(k);
        }
        for (const [sig, members] of bySig) {
          if (members.length < minMembers) continue;
          const gid = `grp:${sig}:${groups.length}`;
          groups.push({
            group_id: gid,
            signature: sig,
            member_count: members.length,
            parent_bbox: rect(parent),
          });
          members.forEach((m, i) => {
            elements.push(Object.assign(describe(m, gid, i, sig), { group_id: gid, role: "member" }));
            // Measure leaf descendants that carry text — these are the prices/labels
            // whose collapse onto one coordinate is the defect we are hunting.
            const leaves = Array.from(m.querySelectorAll("*")).filter(
              (d) => d.children.length === 0 && (d.textContent || "").trim().length > 0
            );
            leaves.forEach((d, j) => {
              const e = describe(d, `${gid}#${i}`, j, sig + " leaf");
              e.group_id = gid;
              e.role = "member_leaf";
              e.member_index = i;
              // structural position within the member, so the evaluator compares like
              // with like across members instead of guessing by document order
              e.leaf_path = (() => {
                const parts = [];
                let cur = d;
                while (cur && cur !== m) {
                  const sibs = Array.from(cur.parentElement ? cur.parentElement.children : []);
                  parts.unshift(`${cur.tagName}:${sibs.indexOf(cur)}`);
                  cur = cur.parentElement;
                }
                return parts.join(">");
              })();
              elements.push(e);
            });
          });
        }
      }
    }
  }

  return {
    probe_version: input.probe_version,
    viewport: { w: window.innerWidth, h: window.innerHeight,
                dpr: window.devicePixelRatio || 1 },
    scroll: { x: Math.round(window.scrollX), y: Math.round(window.scrollY) },
    document_scroll_width: Math.round(document.documentElement.scrollWidth),
    elements: elements,
    groups: groups,
    errors: errors,
  };
}

/**
 * Source string for transports that inject JS rather than pass a function.
 * Evaluates to a function of one argument (the input object).
 */
function probeSource() {
  return `(${__probeBody.toString()})`;
}

export { PROBE_VERSION, DEFAULT_PROPS, __probeBody as probeBody, probeSource };
