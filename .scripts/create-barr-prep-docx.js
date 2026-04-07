const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
        LevelFormat, Header, Footer, PageNumber, PageBreak } = require('docx');

const tb = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const cb = { top: tb, bottom: tb, left: tb, right: tb };

function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 200 }, children: [new TextRun({ text })] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 160 }, children: [new TextRun({ text })] }); }
function h3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 120 }, children: [new TextRun({ text })] }); }
function p(text, opts = {}) { return new Paragraph({ spacing: { after: 120 }, ...opts, children: [new TextRun({ text, ...opts.run })] }); }
function bold(text) { return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, bold: true })] }); }
function mixed(parts) { return new Paragraph({ spacing: { after: 120 }, children: parts.map(([text, opts]) => new TextRun({ text, ...opts })) }); }

function makeTable(headers, rows, colWidths) {
  const hdrCells = headers.map((h, i) => new TableCell({
    borders: cb, width: { size: colWidths[i], type: WidthType.DXA },
    shading: { fill: "2B4C7E", type: ShadingType.CLEAR },
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: h, bold: true, color: "FFFFFF", size: 20, font: "Arial" })] })]
  }));
  const dataRows = rows.map(r => new TableRow({
    children: r.map((c, i) => new TableCell({
      borders: cb, width: { size: colWidths[i], type: WidthType.DXA },
      children: [new Paragraph({ children: [new TextRun({ text: c, size: 20, font: "Arial" })] })]
    }))
  }));
  return new Table({ columnWidths: colWidths, margins: { top: 60, bottom: 60, left: 120, right: 120 },
    rows: [new TableRow({ tableHeader: true, children: hdrCells }), ...dataRows] });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { size: 48, bold: true, color: "1A365D", font: "Arial" }, paragraph: { spacing: { before: 0, after: 60 }, alignment: AlignmentType.CENTER } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, color: "1A365D", font: "Arial" }, paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: "2B4C7E", font: "Arial" }, paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 23, bold: true, color: "3B6DAA", font: "Arial" }, paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bl", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "nl1", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "nl2", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "nl3", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "nl4", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "nl5", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "CONFIDENTIAL — Interview Prep", italics: true, color: "888888", size: 18 })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Regis Hadiaris — Barr Engineering Interview Prep | Page ", size: 18, color: "888888" }), new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" })] })] }) },
    children: [
      // TITLE
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Barr Engineering Panel Interview Prep")] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: "AI Consultant — Senior Level", size: 28, color: "2B4C7E" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 }, children: [new TextRun({ text: "Wednesday, April 8, 2026 | 8:00–9:00am CT | Phone Interview", size: 22, bold: true })] }),

      // LOGISTICS BOX
      mixed([["Call-in: ", { bold: true }], ["(833) 450-1894 | Conference ID: 768 207 576#", {}]]),
      mixed([["Interviewers: ", { bold: true }], ["Phil Fish (VP, Senior Chemical Engineer) + Michelle Schlegel (HR Generalist)", {}]]),
      new Paragraph({ children: [new PageBreak()] }),

      // THE COMPANY
      h1("THE COMPANY"),
      bold("Barr Engineering Co."),
      ...["Founded 1953 by Douglas W. Barr (civil engineer/hydrologist, Harvard, U of M)", "Employee-owned since 1966 — this matters, it shapes culture", "1,000+ engineers, scientists, and technical specialists", "HQ: Minneapolis, MN. Offices across 11 states + 2 Canadian provinces", "Core business: environmental consulting and engineering", "Industries: mining, petroleum refining, power generation, manufacturing, food processing, taconite, ethanol", "Clients: municipalities, government agencies, watershed districts, industrial facilities, attorneys"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),

      h2("Digital Solutions Team"),
      ...["Led by Kyong Song — AI Practice Leader & Senior Data Scientist", "MS Environmental Science & Engineering, BS Biomedical Engineering (Milwaukee School of Engineering)", "12 years in digital technology and analytics", "Focus: digital twins, EMIS, advanced analytics, AI/ML", "Vendor-agnostic approach", "Collaborating with Phil Fish on AI-assisted air permit review — proof point that AI is already being applied internally"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),

      h2("Barr's AI Readiness Framework (from Kyong's published article)"),
      ...["Data quality generation — 'the right data,' not just more data", "Data systems integration — data warehouses, breaking silos", "Cultural transformation — 70% of digital transformations fail due to weak leadership", "Risk mitigation — ethical AI, compliance, security"].map((t, i) => new Paragraph({ numbering: { reference: "nl1", level: 0 }, children: [new TextRun(t)] })),
      new Paragraph({ spacing: { before: 120, after: 200 }, children: [new TextRun({ text: "Key insight: Barr has the data science foundation but needs someone to build the consulting business around it. That's the role.", bold: true, italics: true })] }),

      // THE ROLE
      new Paragraph({ children: [new PageBreak()] }),
      h1("THE ROLE — What They Actually Need"),
      mixed([["Title: ", { bold: true }], ["AI Consultant – Senior Level (Hybrid/Remote)", {}]]),
      mixed([["Team: ", { bold: true }], ["Digital Solutions / AI Practice", {}]]),
      mixed([["Reports to: ", { bold: true }], ["Works with business unit leadership, director of project technology, and project leaders", {}]]),
      p("This is NOT a technical AI/ML role. This is a practice builder:", { run: { bold: true, italics: true } }),
      ...["Service offering development — Define and develop AI-driven consulting services", "Business development & market positioning — Identify client needs, qualify opportunities, craft value propositions", "Client engagement & solution strategy — Understand objectives, pain points, design high-level AI solutions", "Practice growth & management — Monitor pipeline, proposal hit rates, profitability, ROI"].map((t, i) => new Paragraph({ numbering: { reference: "nl2", level: 0 }, children: [new TextRun(t)] })),

      // INTERVIEWERS
      new Paragraph({ children: [new PageBreak()] }),
      h1("YOUR INTERVIEWERS"),
      h2("Phil Fish — VP, Senior Chemical Engineer"),
      ...["10+ years at Barr, air quality permitting and compliance", "BS Chemical Engineering, University of Minnesota-Duluth (you're both Duluth people)", "Works with: petroleum refineries, ethanol, taconite, food processing", "Already using AI: Collaborating with Kyong Song on AI-assisted air permit review"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      h3("What he'll evaluate"),
      ...["Can you understand engineering workflows well enough to identify where AI adds value?", "Can you translate between technical AI capabilities and engineering client needs?", "Are you credible with engineers, not just business people?"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      h3("Your angle"),
      ...["Rocket Mortgage = taking complex, multi-state regulatory process and making it scalable through technology. Same pattern as air quality permitting.", "You built Dot Connector AI — structures expert frameworks into repeatable, auditable workflows. That's exactly what AI-assisted permit review needs.", "Duluth connection — use it. Natural and authentic."].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),

      h2("Michelle Schlegel — HR Generalist (PHR)"),
      ...["Handles recruiting, onboarding, employee relations", "Prior: Culligan Water, Jefferson Lines, Minnesota Children's Museum", "PHR certified"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      h3("What she'll evaluate"),
      ...["Culture fit for an employee-owned engineering firm", "Communication style — can you work alongside engineers without talking over them?", "Compensation alignment, why Barr, genuine interest"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),

      // OPENER
      new Paragraph({ children: [new PageBreak()] }),
      h1("OPENER"),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"Phil, thanks for taking the time. I\'ve been looking forward to this. I spent the last 21 years at Rocket Companies building systems that turned complex regulatory processes into scalable technology — from mortgage compliance across 50 states to financial data standards at the national level. What excites me about Barr is that you\'re at the same inflection point: you have deep domain expertise and strong data science capabilities, and the opportunity is turning that into a client-facing AI practice. I\'ve done exactly that kind of build before, and I\'d love to talk about how it applies here."', italics: true })] }),

      // ANTICIPATED QUESTIONS
      h1("ANTICIPATED QUESTIONS"),

      h2('1. "Walk us through your background."'),
      p("Keep it tight (3 minutes). Phil is an engineer — he respects efficiency.", { run: { italics: true } }),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"Three chapters. First, I built the digital marketing and experimentation foundation at Rocket — A/B testing, personalization, measurement — before most lenders knew what those words meant. Second, I was the product lead for Rocket Mortgage from concept through Super Bowl launch. We took a 45-day mortgage application and compressed it into minutes, which meant rebuilding identity verification, income verification, underwriting, and compliance workflows across all 50 states. Third, I scaled it — $7B to $100B+ in volume, teams of 28+, 50+ product capabilities shipped, 23 J.D. Power #1 rankings. Since leaving in early 2025, I\'ve built Dot Connector AI — 66 structured analytical frameworks deployed for PE due diligence, go-to-market strategy, and competitive intelligence."', italics: true })] }),

      h2('2. "This role is about building an AI consulting practice. Have you done that before?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"Yes — twice. At Rocket, I built the function that turned data and technology capabilities into revenue-generating products driving $100B+ in volume. More recently, I built Dot Connector AI from scratch — 66 frameworks, defining the offering, finding clients, demonstrating value. That\'s exactly the pattern this role requires."', italics: true })] }),

      h2('3. "What do you know about environmental consulting?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"I\'m not an environmental engineer, and I won\'t pretend to be. But the pattern is the same: complex regulatory environments, multi-jurisdiction compliance, large datasets turned into decisions, expert workflows made more efficient with technology. I saw that Phil and Kyong Song are already doing AI-assisted air permit review — the value isn\'t replacing the engineer\'s judgment; it\'s accelerating the analysis. I\'ve done exactly this in mortgage."', italics: true })] }),

      h2('4. "How would you approach building this practice in your first 90 days?"'),
      h3("Days 1-30: Listen and Map"),
      ...["Meet with practice leaders across key verticals (air quality, water, remediation, mining)", "Sit with Kyong Song's team to understand current capabilities", "Talk to 5-10 clients — what are they hearing about AI?", "Audit competitive landscape — Arcadis, WSP, AECOM, Tetra Tech"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      h3("Days 31-60: Define the Offering"),
      ...["Define 2-3 initial AI consulting service packages", "Build value proposition and pricing model", "Create proposal templates and case studies (Phil's air permit review is exhibit A)", "Identify 3-5 pilot clients"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      h3("Days 61-90: Go to Market"),
      ...["Launch pilots with first clients", "Start measuring: pipeline, win rates, revenue, satisfaction", "Present results and refined strategy to leadership", "Establish thought leadership — conferences, published content"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),

      h2('5. "Why Barr?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"Three reasons. First, employee-owned — decisions made for long-term value. I stayed 21 years at one company because I believe in building things that last. Second, this is a build, not an optimize — zero-to-one is where I\'m at my best. Third, I\'m from Duluth. I know Barr, I know the industries you serve, and I know the Midwest engineering culture."', italics: true })] }),

      h2('6. "Your background is in mortgage/fintech. How does that translate?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"The domains are different, but the problems are structurally identical. Mortgage is regulated, multi-jurisdiction, data-intensive, where expert judgment matters. Environmental consulting is the same. I also hold two patents in digital mortgage and income verification — I don\'t just talk about AI, I\'ve built patentable systems."', italics: true })] }),

      h2('7. "What\'s your compensation expectation?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"I\'m looking for total compensation in the range of $180K-$220K, depending on the full package — base, bonus, benefits, and the equity component of employee ownership. I\'m flexible on the mix."', italics: true })] }),

      h2('8. "What are you doing currently?"'),
      new Paragraph({ spacing: { after: 200 }, indent: { left: 360, right: 360 }, children: [new TextRun({ text: '"I\'m a partner at The Wisory, a PE-focused advisory firm where I lead product strategy and AI tooling. I also run Dot Connector Dispatch, a strategy newsletter with 600+ subscribers. Both keep me sharp — but I\'m looking for an operating role where I can build something at scale. Barr is exactly that opportunity."', italics: true })] }),

      // QUESTIONS TO ASK
      new Paragraph({ children: [new PageBreak()] }),
      h1("QUESTIONS TO ASK"),
      h3("For Phil"),
      ...['1. "You\'ve been working with Kyong on AI-assisted air permit review. What surprised you about how AI performed vs. what you expected?"', '2. "Where do your engineers spend the most time on work that feels repetitive or low-leverage?"', '3. "What would success look like for this role from your perspective?"'].map(t => new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t })] })),
      h3("For Michelle"),
      ...['4. "Barr has been employee-owned since 1966. How does that shape the culture day-to-day?"', '5. "What does professional development look like for senior hires?"'].map(t => new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: t })] })),
      h3("For Both"),
      new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: '6. "If this AI practice is thriving in two years, what does it look like? How many people, what kinds of clients, what services?"' })] }),

      // KEY DIFFERENTIATORS TABLE
      h1("KEY DIFFERENTIATORS"),
      makeTable(["Differentiator", "How to Use It"], [
        ["21 years at one company", "Loyalty, depth, commitment — mirrors employee-ownership culture"],
        ["Duluth connection", "Phil went to UMD, you live in Duluth. Authentic Midwest fit."],
        ["Regulatory complexity at scale", "50-state mortgage compliance → multi-jurisdiction environmental permitting"],
        ["Zero-to-one builder", "Rocket Mortgage (concept → $100B), Dot Connector AI (0 → 66 frameworks), FDX (founding board)"],
        ["2 patents", "Not just a talker — you've built patentable technology"],
        ["AI literacy + business acumen", "The JD says business role, not deep technical. You're the rare person who can do both."],
        ["Employee-owned fit", "You stayed 21 years at Rocket. You build for the long term."],
      ], [3500, 5860]),

      // NUMBERS TABLE
      new Paragraph({ children: [new PageBreak()] }),
      h1("NUMBERS TO HAVE READY"),
      makeTable(["Metric", "Number"], [
        ["Rocket tenure", "21 years (2004–2025)"],
        ["Platform scale", "$7B → $100B+ annual volume"],
        ["Clients served", "2.8M"],
        ["Client retention", "97%"],
        ["J.D. Power #1 rankings", "23"],
        ["Patents", "2 (digital mortgage + income verification)"],
        ["Team size", "28+ cross-functional; 500+ technology org"],
        ["Truebill acquisition", "$1B"],
        ["Products shipped", "50+ capabilities"],
        ["FDX founding", "2017"],
        ["Dot Connector frameworks", "66 structured analytical vectors"],
        ["Patentable inventions", "5 identified"],
        ["Newsletter subscribers", "600+"],
      ], [4000, 5360]),

      // WATCH OUT FOR
      h1("WATCH OUT FOR"),
      ...["Don't oversell AI hype. Barr is an engineering firm. Talk measurable outcomes, not buzzwords.", "Don't dismiss the domain. Show respect for environmental consulting's complexity.", "Don't talk over Phil. Let him lead when he wants to. Listen more than you talk.", "This is a phone interview. No visual cues. Smile when you talk. Leave pauses.", "Employee-owned culture = humility matters. Come in as a builder, not a transformer."].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, spacing: { after: 100 }, children: [new TextRun(t)] })),

      // COMPETITIVE LANDSCAPE
      h1("COMPETITIVE LANDSCAPE"),
      ...["Arcadis — Global environmental consultancy, investing in digital solutions", "WSP — Large engineering firm with growing data/analytics practice", "AECOM — Huge infrastructure firm, AI/digital twin initiatives", "Tetra Tech — Environmental services, some AI adoption"].map(t => new Paragraph({ numbering: { reference: "bl", level: 0 }, children: [new TextRun(t)] })),
      new Paragraph({ spacing: { before: 120, after: 200 }, children: [new TextRun({ text: "Barr's advantage: employee-owned (long-term thinking), deep domain expertise, Kyong's AI practice as foundation. The gap: no client-facing AI consulting offering yet. That's the job.", bold: true, italics: true })] }),

      // FOOTER
      new Paragraph({ spacing: { before: 400 }, children: [] }),
      new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Prepared: April 7, 2026 | Interview: Wednesday, April 8, 2026, 8:00am CT", italics: true, color: "888888", size: 18 })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Call-in: (833) 450-1894 | Conference ID: 768 207 576#", italics: true, color: "888888", size: 18 })] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  const outPath = "/Users/regishadiaris/Google Drive/My Drive/1 - Projects/Job Search/Barr_Interview_Prep.docx";
  fs.writeFileSync(outPath, buffer);
  console.log("✅ Saved to: " + outPath);
});
