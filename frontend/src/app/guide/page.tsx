import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  BookOpen,
  Building2,
  CalendarCheck,
  CalendarRange,
  Download,
  FileSpreadsheet,
  HardHat,
  Landmark,
  ListChecks,
  ListFilter,
  Mail,
  NotebookPen,
  Receipt,
  Repeat,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Table2,
  Upload,
  Users,
  Wallet,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { FaqSearch } from "@/components/guide/FaqSearch";
import { GuideTabs } from "@/components/guide/GuideTabs";

export const metadata = { title: "Guide · LedgerMind" };

const CLIENT_TYPES: { icon: LucideIcon; title: string; when: string; files: string[] }[] = [
  {
    icon: FileSpreadsheet,
    title: "Xero, QuickBooks or Sage",
    when: "The client keeps books in software.",
    files: ["Trial balance", "General ledger", "Aged debtors and creditors (optional)", "Last year's TB (optional)",
            "Sage: pick the columns once when asked; the app remembers them"],
  },
  {
    icon: Landmark,
    title: "Bank + Dext",
    when: "No software: the books are prepared in the app.",
    files: ["Bank statement (one per account)", "Dext sales and bills", "Last year's TB", "Last year's unpaid invoices and bills"],
  },
  {
    icon: Wallet,
    title: "Bank only",
    when: "Only bank and card statements: the app sorts every line.",
    files: ["Bank and card statements (one per account)", "Last year's TB", "Sales list, if there is one"],
  },
];

/** Extra files: each one turns on more checks and better figures. */
const EXTRA_FILES: { icon: LucideIcon; title: string; where: string; unlocks: string[] }[] = [
  {
    icon: CalendarCheck, title: "Last year's TB", where: "Upload, with the TB",
    unlocks: ["Opening balances for every account (loans, DLA, fixed assets)", "Last year vs this year and the big-change questions",
              "Without it, balances that only open the year (a loan with no payments) can be missed"],
  },
  {
    icon: Receipt, title: "VAT summary", where: "VAT area, Evidence tab",
    unlocks: ["Each return matched to its HMRC payment (interest and penalties kept apart)", "Box 6 against sales, cash or accrual basis, flat rate"],
  },
  {
    icon: Users, title: "Payroll file", where: "Net wages and payroll area, Evidence tab",
    unlocks: ["Directors' pay split from staff wages, with the journal", "Employer NI (after the employment allowance) and pension against the books",
              "Average number of employees", "Subcontractor v employee check (who is on the payroll)"],
  },
  {
    icon: Landmark, title: "Loans and HP register", where: "Loans and HP area, Evidence tab: *Download template*, fill in, upload",
    unlocks: ["Each loan's balance, due within / after one year and interest, from the agreement",
              "Journals: interest not charged, and the split between within and after one year"],
  },
  {
    icon: Building2, title: "Fixed asset register", where: "Fixed assets area, Evidence tab",
    unlocks: ["Depreciation and the fixed asset schedule", "Capital allowances for the tax computation"],
  },
  {
    icon: HardHat, title: "CIS figures from HMRC", where: "Net wages and payroll area, Evidence tab",
    unlocks: ["CIS deducted and suffered month by month against the CIS300 / EPS", "The CIS reconciliation tabs (G7.2, G7.3)"],
  },
];

/** The latest additions, newest first: update with each release. */
const WHATS_NEW: { title: string; text: string }[] = [
  { title: "Loans and HP from the agreement", text: "Upload the loans register: each loan's balance, split, interest and journals from the schedule." },
  { title: "Directors' pay and payroll", text: "Directors' pay split from wages; employer NI, pension and the employment allowance checked against the payroll file." },
  { title: "Subcontractors and CIS", text: "Subcontractor v employee flags (G6.4) and the CIS tabs by HMRC month (G7.2, G7.3)." },
  { title: "VAT", text: "VAT summary upload: each return matched to its HMRC payment; Box 6, cash basis and flat rate checks." },
  { title: "Sage ledgers", text: "More Sage reports read (Nominal Activity, Intacct)." },
];

/** Files to download: the loans register to fill in, and samples of the layouts read best. */
const DOWNLOADS: { title: string; text: string; href: string }[] = [
  { title: "Loans and HP register", text: "Fill in one row per agreement, then upload it on the Loans and HP area's Evidence tab.",
    href: "/templates/loans-register-template.xlsx" },
  { title: "Payroll summary (sample)", text: "The layout read best: one row per month, directors' pay on its own line.",
    href: "/templates/payroll-summary-sample.xlsx" },
  { title: "Fixed asset register (sample)", text: "One block per class with its rate, one row per asset.",
    href: "/templates/far-sample.xlsx" },
];

/** Where the main checks are in the downloaded workbook. */
const WORKBOOK_TABS: { tab: string; what: string }[] = [
  { tab: "A1 - General checks", what: "The app's checks on the whole file" },
  { tab: "B1-ETB / B2-Journals", what: "Extended trial balance and the approved journals" },
  { tab: "E2 / G2", what: "Debtors and creditors against the aged lists" },
  { tab: "G2.3", what: "Duplicates review" },
  { tab: "G3", what: "Director's loan account; G3.2 related parties" },
  { tab: "G4", what: "Loans and HP: one tab per loan, with the schedule when the register is uploaded" },
  { tab: "G6.2", what: "Payroll summary, directors' pay against the payroll file" },
  { tab: "G6.3 / G6.4", what: "Average employees; subcontractor v employee" },
  { tab: "G7 / G8", what: "PAYE and pension control accounts; G7.2 / G7.3 CIS" },
  { tab: "G9", what: "VAT control, returns and payments" },
  { tab: "H1 / H2", what: "Corporation tax computation and CT600 boxes" },
];

/** Before upload: what each file should be, from the mistakes seen in real uploads. */
const PREPARE: { group: string; items: string[] }[] = [
  {
    group: "Every file",
    items: [
      "The *same year end* for every file: TB, ledger, aged lists, payroll and VAT all cover the same year.",
      "Exported straight from the software, as Excel or CSV. *No hand-typed figures*, no merged cells, no deleted columns.",
      "Don't upload the app's own workbook or last year's working papers as inputs.",
    ],
  },
  {
    group: "Trial balances",
    items: [
      "*This year's TB*: at the year end, with debits equal to credits.",
      "If the software gives only *this year's movements* (no share capital or reserves in it), add *last year's closing TB* too.",
      "*Last year's TB*: the final one, after last year's journals. It must add up to zero; a heading row (Code, Account, Debit, Credit) is best.",
    ],
  },
  {
    group: "Ledger and reports",
    items: [
      "*General ledger*: the full year (Xero / QuickBooks / Sage detailed report), with the opening balances.",
      "*Aged debtors and creditors*: the summary at the year-end date, with totals.",
      "*Payroll*: the summary for the whole year, not monthly payslips.",
      "*VAT*: the returns for the periods in the year, as filed with HMRC.",
      "*Bank*: the year-end statement balance of each account.",
    ],
  },
  {
    group: "After upload",
    items: [
      "Check what each file is *read as* before you click *Upload*.",
      "Fix every red point on the *Files* tab first. First year of trading? Tick it there.",
      "Don't press *Confirm all* without looking: check the codes the AI suggested.",
    ],
  },
];

const STEPS: { icon: LucideIcon; title: string; click: string; get: string; only?: string }[] = [
  {
    icon: Upload, title: "Upload",
    click: "On Clients, click *New client* and drop the files. Check what each file is read as, then *Upload*.",
    get: "The client's page opens with every account already mapped.",
  },
  {
    icon: ShieldCheck, title: "Files",
    click: "Fix what is red (it stops the workbook) and look at what is amber. Upload a missing file here.",
    get: "Inputs you can trust: the TB balances and last year's balances are in.",
  },
  {
    icon: SlidersHorizontal, title: "Setup",
    click: "Answer the questions: VAT registered? Payroll? Directors? Then *Save*.",
    get: "The checks that fit this client: VAT checks only if VAT registered, and so on.",
  },
  {
    icon: BookOpen, title: "Books", only: "Bank + Dext / bank",
    click: "Look at the yellow bank lines and pick what each one is. Then *Make trial balance*.",
    get: "The books from the bank statement and Dext: sales, bills, debtors and creditors.",
  },
  {
    icon: Table2, title: "Accounts",
    click: "Check each account's code. *Confirm* if right, *Change* if not. *Confirm all* does the sure ones at once.",
    get: "Every balance in the right place in the accounts.",
  },
  {
    icon: Receipt, title: "Evidence on each area",
    click: "On the VAT area's Evidence tab, enter the VAT returns or upload the *VAT summary*. Upload the payroll file, fixed asset register and *loans register* on their areas' Evidence tabs, and enter CIS figures on Payroll's, if the client has them.",
    get: "The books checked against HMRC, the payroll and the loan agreements.",
  },
  {
    icon: ListChecks, title: "Review",
    click: "Click *Run review*. Read each point: *Clear point* if fine, or tick it for the client email.",
    get: "A list of what to fix or ask, and the corporation tax worked out.",
  },
  {
    icon: NotebookPen, title: "Journals",
    click: "*Approve* or *Reject* each suggested adjustment. *New journal* adds your own.",
    get: "Approved journals go into the final figures and the workbook.",
  },
  {
    icon: FileSpreadsheet, title: "Finish and download",
    click: "Click *Build Excel*, then *Download Excel*.",
    get: "The full Excel working papers, ready to file.",
  },
];

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Mail, title: "Client email", text: "Open questions as a ready email to copy. Nothing is sent from the app." },
  { icon: CalendarRange, title: "Last year vs this year", text: "Both years side by side; big changes become client questions." },
  { icon: Repeat, title: "Once per supplier", text: "Choose a head for one line and apply it to every line from that supplier." },
  { icon: ListFilter, title: "Mapping", text: "Your firm's own rules, and the codes it remembers, used for every client." },
  { icon: Sparkles, title: "Remembers your choices", text: "Codes and heads you set are used again next year." },
  { icon: Receipt, title: "Corporation tax", text: "The tax computation is worked out from the final figures." },
];

const FAQ: { group: string; items: { q: string; a: string }[] }[] = [
  {
    group: "Common questions",
    items: [
      {
        q: "I can't click Build Excel. Why?",
        a: "The button at the top of a client stays faded until four things are done: no red points left on the Files tab, the Setup questions answered, every account checked on the Accounts tab, and the review run after the last change. The small line under the button tells you which one is left.",
      },
      {
        q: "Do I upload one file or separate files?",
        a: "Either. One workbook with tabs, or separate files: the app reads each one and shows what it thinks it is. If it guessed wrong, change it in the list before you click Upload.",
      },
      {
        q: "I uploaded the wrong files.",
        a: "Upload again for the same client and the same year end. The earlier upload is replaced. A different year end makes a new year for that client and keeps the old one.",
      },
      {
        q: "Does the app email the client?",
        a: "No. *Make client email* gives a ready email with the questions. Copy it and send it from your own email.",
      },
      {
        q: "Where do I see last year?",
        a: "On the Accounts tab, in the Last year and Change columns. They fill in when last year's job is in the app or you uploaded last year's TB. Big changes are added to the Review as client questions.",
      },
      {
        q: "I changed something after building the workbook.",
        a: "*Run review* again, then *Build Excel* again. The Excel file always shows the figures at the time it was built.",
      },
      {
        q: "Why did the app move directors' pay out of wages?",
        a: "The payroll file shows the directors' pay (a 'Director Salary' line or a block per director) and the books have it in staff wages. Directors' pay is shown on its own in the accounts, so a journal to *directors' salaries* is proposed. Approve or reject it on the Journals tab.",
      },
      {
        q: "Why is no employment allowance proposed?",
        a: "It is not available when everyone paid above the NI threshold is a director, or when the books already hold it. If the payroll file shows the allowance claimed, that amount is used.",
      },
      {
        q: "What do the subcontractor flags A to D mean?",
        a: "A: on the payroll and also paid as a subcontractor. B: paid as a subcontractor in 6 or more months (employment status, CIS). C: paid through wages but not on the payroll. D: paid in 3 or more months (£1,000 or more) through cost accounts. Each is a question for the client, listed on G6.4.",
      },
      {
        q: "A loan tab says the balance comes from the ledger. Why?",
        a: "The TB has only this year's movements and no opening balance for that loan, but the ledger opens it with one. The tab shows it so the loan is not missed; post last year's balance, or upload last year's TB.",
      },
      {
        q: "Will the app remember my choices next year?",
        a: "Yes. Codes you confirm or change, and heads you choose for a supplier, are used again for the same client next year.",
      },
    ],
  },
  {
    group: "Words used in the app",
    items: [
      { q: "Mapping / code", a: "Each client account is put on a line of the firm's standard chart, for example “Tesco fuel” to 3230 Vehicle running costs. That line number is the code." },
      { q: "Head", a: "What a bank line is for, such as Telephone, Fuel or Rent. Used for Bank + Dext clients." },
      { q: "Suspense", a: "A holding place for amounts the app could not place. Pick a head or code for them, or ask the client." },
      { q: "Point", a: "Something the review found that needs a look: a check that failed, or a question for the client." },
      { q: "Journal", a: "An adjustment to the figures, such as depreciation or an accrual. The app suggests them; you approve them." },
      { q: "Trial balance (TB)", a: "The list of every account and its balance at the year end. Everything in the workbook is built from it." },
    ],
  },
];

/** How to use the app, in brief: for the accountant, not how it works inside. */
export default function GuidePage() {
  return (
    <div className="mx-auto max-w-5xl space-y-8 pb-6">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-teal-800 via-teal-700 to-teal-600 px-6 py-6 text-white shadow-sm sm:px-10">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-white/10" />
        <div className="pointer-events-none absolute -bottom-20 right-24 h-40 w-40 rounded-full bg-white/10" />
        <p className="text-[11px] font-semibold uppercase tracking-widest text-teal-100">Guide</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">From client files to working papers</h1>
        <p className="mt-2 max-w-xl text-sm text-teal-50">
          Upload the client&apos;s files, check what the app flags, and download a reviewed Excel workbook.
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-medium">
          {["Upload", "Check", "Download"].map((s, i) => (
            <span key={s} className="flex items-center gap-2">
              <span className="rounded-full bg-white/20 px-3 py-1 backdrop-blur">{i + 1}. {s}</span>
              {i < 2 && <ArrowRight className="h-3.5 w-3.5 text-teal-100" />}
            </span>
          ))}
        </div>
      </section>

      <GuideTabs
        tabs={[
          {
            id: "start", label: "Get started",
            content: (
              <>
              {/* What's new */}
              <section>
                <Card className="border-teal-200 bg-teal-50/40 p-5">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-teal-700" />
                    <h2 className="text-sm font-semibold text-slate-900">What&apos;s new</h2>
                  </div>
                  <ul className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {WHATS_NEW.map(({ title, text }) => (
                      <li key={title} className="flex gap-2 text-xs leading-relaxed text-slate-700">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                        <span><strong className="font-semibold text-slate-900">{title}.</strong> {text}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              </section>
              {/* Client types */}
              <section id="client-types" className="scroll-mt-20">
                <SectionTitle title="Three kinds of client" text="Pick the one that fits; the steps after upload are the same." />
                <div className="grid gap-4 md:grid-cols-3">
                  {CLIENT_TYPES.map(({ icon: Icon, title, when, files }) => (
                    <Card key={title} className="p-5 hover:border-teal-200 hover:shadow-sm">
                      <div className="flex items-center gap-3">
                        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-700">
                          <Icon className="h-5 w-5" />
                        </span>
                        <div>
                          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
                          <p className="text-xs text-slate-500">{when}</p>
                        </div>
                      </div>
                      <ul className="mt-4 space-y-1.5 text-xs text-slate-700">
                        {files.map((f) => (
                          <li key={f} className="flex items-center gap-2">
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                            {f}
                          </li>
                        ))}
                      </ul>
                    </Card>
                  ))}
                </div>
              </section>
              {/* Steps */}
              <section id="steps" className="scroll-mt-20">
                <SectionTitle title="Step by step" text="The tabs of a client, left to right: what to click, and what you get." />
                <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {STEPS.map(({ icon: Icon, title, click, get, only }, i) => (
                    <li key={title}>
                      <Card className="flex h-full flex-col p-4 hover:border-teal-200">
                        <div className="flex items-center justify-between">
                          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white">
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="font-mono text-[11px] font-semibold text-slate-300">0{i + 1}</span>
                        </div>
                        <h3 className="mt-3 text-sm font-semibold text-slate-900">{title}</h3>
                        <p className="mt-1.5 text-xs leading-relaxed text-slate-700">{bold(click)}</p>
                        <p className="mt-2 border-t border-slate-100 pt-2 text-[11px] leading-relaxed text-slate-500">
                          <span className="font-semibold text-emerald-700">You get: </span>{get}
                        </p>
                        {only && (
                          <span className="mt-3 w-fit rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
                            {only} only
                          </span>
                        )}
                      </Card>
                    </li>
                  ))}
                </ol>
              </section>
              {/* Features */}
              <section>
                <SectionTitle title="Handy to know" />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {FEATURES.map(({ icon: Icon, title, text }) => (
                    <div key={title} className="flex gap-3 rounded-xl border border-slate-200/80 bg-white p-4">
                      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
                      <div>
                        <h3 className="text-xs font-semibold text-slate-900">{title}</h3>
                        <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
              </>
            ),
          },
          {
            id: "files", label: "Files", anchors: ["before-upload", "extra-files", "downloads"],
            content: (
              <>
              {/* Before upload */}
              <section id="before-upload" className="scroll-mt-20">
                <SectionTitle
                  title="Before you upload: get the files right"
                  text="Most wrong figures come from the files, not the app. Check these first."
                />
                <div className="grid gap-3 sm:grid-cols-2">
                  {PREPARE.map(({ group, items }) => (
                    <Card key={group} className="p-4">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-teal-700">{group}</h3>
                      <ul className="mt-2.5 space-y-2">
                        {items.map((item) => (
                          <li key={item} className="flex gap-2 text-xs leading-relaxed text-slate-700">
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                            <span>{bold(item)}</span>
                          </li>
                        ))}
                      </ul>
                    </Card>
                  ))}
                </div>
              </section>
              {/* Extra files */}
              <section id="extra-files" className="scroll-mt-20">
                <SectionTitle
                  title="Extra files and what they unlock"
                  text="Optional, but each one turns on more checks and better figures."
                />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {EXTRA_FILES.map(({ icon: Icon, title, where, unlocks }) => (
                    <Card key={title} className="p-4 hover:border-teal-200">
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                          <Icon className="h-4 w-4" />
                        </span>
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
                          <p className="text-[11px] text-slate-500">{bold(where)}</p>
                        </div>
                      </div>
                      <ul className="mt-3 space-y-1.5">
                        {unlocks.map((u) => (
                          <li key={u} className="flex gap-2 text-xs leading-relaxed text-slate-700">
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
                            <span>{u}</span>
                          </li>
                        ))}
                      </ul>
                    </Card>
                  ))}
                </div>
              </section>
              {/* Downloads */}
              <section id="downloads" className="scroll-mt-20">
                <SectionTitle title="Downloads" text="The loans register to fill in, and samples of the layouts the app reads best." />
                <div className="grid gap-3 sm:grid-cols-3">
                  {DOWNLOADS.map(({ title, text, href }) => (
                    <a key={href} href={href} download
                       className="group flex flex-col rounded-xl border border-slate-200/80 bg-white p-4 transition hover:border-teal-300 hover:shadow-sm">
                      <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                        <Download className="h-4 w-4 text-teal-700" /> {title}
                      </span>
                      <span className="mt-1 text-xs leading-relaxed text-slate-500">{text}</span>
                      <span className="mt-3 text-[11px] font-semibold text-teal-700 group-hover:underline">Download .xlsx</span>
                    </a>
                  ))}
                </div>
              </section>
              </>
            ),
          },
          {
            id: "workbook", label: "Finish and download", anchors: [],
            content: (
              <>
              {/* Workbook map */}
              <section>
                <SectionTitle title="Where to find it in the workbook" text="The main checks, by tab." />
                <Card className="divide-y divide-slate-100 p-0">
                  {WORKBOOK_TABS.map(({ tab, what }) => (
                    <div key={tab} className="flex flex-col gap-0.5 px-5 py-2.5 sm:flex-row sm:items-center sm:gap-4">
                      <span className="w-40 shrink-0 font-mono text-xs font-semibold text-teal-700">{tab}</span>
                      <span className="text-xs text-slate-700">{what}</span>
                    </div>
                  ))}
                </Card>
              </section>
              </>
            ),
          },
          {
            id: "questions", label: "Questions", anchors: [],
            content: (
              <>
              {/* FAQ */}
              <section>
                <SectionTitle title="Questions" text="Common questions and the words used in the app." />
                <FaqSearch groups={FAQ} />
              </section>
              </>
            ),
          },
        ]}
      />

      {/* Start */}
      <section className="flex flex-col items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-6 py-5 sm:flex-row">
        <p className="text-sm font-medium text-slate-800">Ready? Start with a new client.</p>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 rounded-lg bg-teal-700 px-4 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-teal-800"
        >
          Go to clients <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </section>
    </div>
  );
}

/** *Button name* in the text, shown in bold. */
function bold(text: string) {
  return text.split("*").map((part, i) => (i % 2 ? <strong key={i} className="font-semibold text-slate-900">{part}</strong> : part));
}

function SectionTitle({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-base font-semibold tracking-tight text-slate-900">{title}</h2>
      {text && <p className="text-xs text-slate-500">{text}</p>}
    </div>
  );
}
