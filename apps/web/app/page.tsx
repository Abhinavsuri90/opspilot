import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { PublicBrand } from "@/components/PublicBrand";
import styles from "./landing.module.css";

export const metadata: Metadata = {
  title: "OpsPilot | A clearer way to work through invoices",
  description: "Bring invoice intake, source documents, team reviews, and verified totals into one organization workspace. Create your organization or join your team.",
};

function Icon({ name }: { name: "arrow" | "document" | "people" | "check" | "shield" | "chart" | "layers" | "menu" }) {
  const paths: Record<typeof name, ReactNode> = {
    arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
    document: <><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5M9 12h6M9 16h6" /></>,
    people: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M21 21v-2a6 6 0 0 0-4-5.65" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" /><path d="m8 12 3 3 5-6" /></>,
    chart: <path d="M4 3v17h17M9 15V9M14 15V5M19 15v-4" />,
    layers: <path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5" />,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  };
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

const roles = [
  { name: "Organization admin", eyebrow: "BUILD YOUR WORKSPACE", icon: "shield" as const, description: "Bring your company, people, and invoice process together.", points: ["Create your organization", "Approve teammates and assign roles", "Manage categories and review access"], label: "Create an organization", href: "/register?mode=create" },
  { name: "Team member", eyebrow: "KEEP WORK MOVING", icon: "people" as const, description: "Get invoices to the right people, with the context they need.", points: ["Join an existing organization", "Upload invoices and inspect their source", "Discuss invoices with your team"], label: "Join as a member", href: "/register?mode=join&role=member" },
  { name: "Invoice reviewer", eyebrow: "MAKE INFORMED DECISIONS", icon: "check" as const, description: "See the source, check the details, and leave a clear decision.", points: ["Request reviewer access", "Verify amounts and invoice categories", "Approve, reject, or reopen eligible invoices"], label: "Join as a reviewer", href: "/register?mode=join&role=reviewer" },
];

const pages = [
  ["01", "Dashboard", "Your organization at a glance. See invoice counts and recent activity."],
  ["02", "Inbox", "Upload PDFs, find invoices, read source evidence, and collaborate."],
  ["03", "Review", "A focused queue for invoices that still need a decision."],
  ["04", "Actions", "Inspect and approve follow-up work before a connector runs."],
  ["05", "Insights", "Explore verified totals by currency and ask invoice questions."],
  ["06", "Admin", "Approve teammates, manage roles, and organize invoice categories."],
];

const faqs = [
  ["Should I create an organization or join one?", "Create an organization if you are setting up OpsPilot for your company. You become its administrator. If your team already has a workspace, choose Member or Reviewer, find your organization, and request access."],
  ["Do members and reviewers use different sign-in pages?", "Everyone uses the same sign-in page with an organization, email, and password. Your approved role determines which pages and actions you can access. Choosing a role during registration sends a request to your administrator."],
  ["What happens after I request access?", "Your membership stays pending until an organization admin approves it and confirms your role. Let your admin know you have registered. After approval, sign in to your chosen organization."],
  ["Who can see my organization's invoices?", "Active teammates can see workspace-visible invoices. Restricted invoices are available only to admins, their uploader, their assigned reviewer, and selected teammates. Shared links still require an approved account with access."],
  ["What kinds of invoices can I upload?", "OpsPilot supports unencrypted PDFs with selectable text, up to 10 MB and 10 pages. Scanned image invoices need OCR, which is not currently available. Extraction results include source evidence and still require a person to verify them."],
];

export default function Home() {
  return <div className={styles.site}>
    <a href="#main-content" className={styles.skipLink}>Skip to content</a>
    <header className={styles.header}><div className={`${styles.container} ${styles.headerInner}`}>
      <PublicBrand className={styles.brand} />
      <nav className={styles.desktopNav} aria-label="Main navigation"><a href="#workflow">How it works</a><a href="#features">The workspace</a><a href="#workspace">For your team</a></nav>
      <div className={styles.headerActions}><Link href="/login" className={styles.signIn}>Sign in</Link><a href="#workspace" className={`${styles.button} ${styles.buttonSmall}`}>Get started <Icon name="arrow" /></a></div>
      <details className={styles.mobileNav}><summary aria-label="Open navigation"><Icon name="menu" /></summary><nav aria-label="Mobile navigation"><a href="#workflow">How it works</a><a href="#features">The workspace</a><a href="#workspace">Choose your role</a><Link href="/login">Sign in</Link></nav></details>
    </div></header>

    <main id="main-content" tabIndex={-1}>
      <section className={`${styles.container} ${styles.hero}`} aria-labelledby="hero-title">
        <div className={styles.heroCopy}>
          <p className={styles.pill}><span /> INVOICE OPERATIONS, TOGETHER</p>
          <h1 id="hero-title">Less chasing.<br />More <span>clarity.</span></h1>
          <p className={styles.heroDescription}>From the first upload to the final review. Give every invoice a place, every teammate a role, and every decision a clear record.</p>
          <div className={styles.heroActions}><Link href="/register?mode=create" className={styles.button}>Create your workspace <Icon name="arrow" /></Link><a href="#workflow" className={styles.textButton}>See how it works <span aria-hidden="true">↗</span></a></div>
          <p className={styles.joinPrompt}>Already part of a team? <a href="#workspace">Find your way in <span aria-hidden="true">→</span></a></p>
          <div className={styles.heroNotes}><span><Icon name="check" /> Your own organization</span><span><Icon name="check" /> People stay in control</span></div>
        </div>
        <div className={styles.previewScene}>
          <div className={styles.previewGlow} aria-hidden="true" />
          <div className={styles.preview} role="img" aria-label="Illustrative workspace with sample invoices moving from intake to review and approval. This preview contains fictional data.">
            <div className={styles.previewTop}><span className={styles.previewLogo}><Icon name="layers" /> OpsPilot</span><span className={styles.previewLabel}>PRODUCT PREVIEW</span></div>
            <div className={styles.previewBody}>
              <div className={styles.previewHeading}><div><p>YOUR WORKSPACE</p><h2>Everything in its place.</h2></div><span className={styles.previewAvatar}>YO</span></div>
              <div className={styles.previewStages}><span><i /> Intake</span><b aria-hidden="true">→</b><span className={styles.stageActive}><i /> Review</span><b aria-hidden="true">→</b><span><i /> Decision</span></div>
              <div className={styles.previewTableHeading}><span>INVOICE</span><span>STATUS</span></div>
              {[['Office supplies', 'INV-001 · Operations', false], ['Software subscription', 'INV-002 · Software', true], ['Travel expenses', 'INV-003 · Travel', false]].map(([name, number, approved]) => <div className={styles.previewInvoice} key={String(number)}><span className={styles.documentIcon}><Icon name="document" /></span><div><strong>{name}</strong><small>{number}</small></div><span className={approved ? styles.statusApproved : styles.statusReview}>{approved && <Icon name="check" />}{approved ? "Approved" : "Needs review"}</span></div>)}
              <div className={styles.previewEvidence}><span><Icon name="shield" /></span><div><strong>Review with the source in view</strong><p>Original PDF. Extracted evidence. Your decision.</p></div></div>
            </div>
          </div>
          <div className={styles.previewCaption}><span className={styles.captionLine} /> A shared view. A clear next step. <span className={styles.captionLine} /></div>
          <p className={styles.sampleNote}>Illustrative workspace · fictional invoice data</p>
        </div>
      </section>

      <div className={styles.principles}><div className={styles.container}>{[["people", "One organization, one workspace"], ["shield", "Admin-approved access"], ["document", "Evidence beside every review"], ["layers", "A history of decisions"]].map(([icon, label]) => <span key={label}><Icon name={icon as "people" | "shield" | "document" | "layers"} />{label}</span>)}</div></div>

      <section id="workspace" className={`${styles.container} ${styles.section}`} aria-labelledby="roles-title">
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>A PLACE FOR EVERYONE</p><h2 id="roles-title">Your team.<br />Working in the same direction.</h2></div><p>Start a workspace or join the people you work with. Access is clear from the very first step.</p></div>
        <div className={styles.roleGrid}>{roles.map((role, index) => <article className={`${styles.roleCard} ${index === 0 ? styles.ownerCard : ""}`} key={role.name}>
          <div className={styles.roleTop}><span className={styles.roleIcon}><Icon name={role.icon} /></span><span className={styles.roleNumber}>0{index + 1}</span></div>
          <p className={styles.roleEyebrow}>{role.eyebrow}</p><h3>{role.name}</h3><p className={styles.roleDescription}>{role.description}</p>
          <ul>{role.points.map(point => <li key={point}><Icon name="check" />{point}</li>)}</ul>
          <Link href={role.href} className={styles.roleLink}>{role.label}<Icon name="arrow" /></Link><p className={styles.roleFootnote}>{index === 0 ? "You become your organization's admin." : "Your organization's admin approves your access."}</p>
        </article>)}</div>
        <p className={styles.existingAccount}>Already approved? <Link href="/login">Sign in to your organization <span aria-hidden="true">→</span></Link></p>
      </section>

      <section id="workflow" className={styles.workflow} aria-labelledby="workflow-title"><div className={`${styles.container} ${styles.workflowInner}`}>
        <div className={styles.workflowIntro}><p className={styles.eyebrow}>FROM INTAKE TO OUTCOME</p><h2 id="workflow-title">A better handoff.<br />At every step.</h2><p>Keep documents, conversations, and decisions connected—so the next person has the context they need.</p><Link href="/register?mode=create" className={`${styles.button} ${styles.buttonLight}`}>Bring your team together <Icon name="arrow" /></Link><div className={styles.workflowMotif} aria-hidden="true"><span><Icon name="document" /></span><i /><span><Icon name="people" /></span><i /><span><Icon name="check" /></span></div></div>
        <ol className={styles.steps}>{[
          ["01", "Upload once. Keep the source.", "Add a text-based PDF to your organization. Extraction runs in the background, keeping the original document and source evidence together."],
          ["02", "Put the right eyes on it.", "An admin assigns a reviewer. Check the full PDF, verify the amount and currency, set a category, and discuss anything that needs attention."],
          ["03", "Make a decision you can trace.", "Approve, reject with a reason, or reopen for another look. Decisions stay in the history, while Insights shows verified totals by currency."],
        ].map(([number, title, description]) => <li key={number}><span>{number}</span><div><h3>{title}</h3><p>{description}</p></div></li>)}</ol>
      </div></section>

      <section id="features" className={`${styles.container} ${styles.section}`} aria-labelledby="features-title">
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>ROOM TO DO THE WORK</p><h2 id="features-title">The details matter.<br />Keep them close.</h2></div><p>A connected workspace for the everyday work around an invoice.</p></div>
        <div className={styles.featureGrid}>
          <article className={styles.documentFeature}><div><span className={styles.featureIcon}><Icon name="document" /></span><h3>The full picture.<br />Right beside the details.</h3><p>Read every PDF page, zoom in, and compare extracted fields with their source. Add a comment without losing the context.</p></div><div className={styles.paperScene} aria-hidden="true"><div className={styles.paperBack} /><div className={styles.paper}><span>INVOICE</span><span className={styles.paperStamp}>SOURCE PDF</span><i /><i /><div className={styles.paperHighlight}><span>Invoice total</span><b>Verified by a person</b></div><i /><i /></div><span className={styles.paperAnnotation}><Icon name="check" /> Evidence in view</span></div></article>
          <article className={styles.insightsFeature}><span className={styles.featureIcon}><Icon name="chart" /></span><h3>Ask a clearer question.<br />Get a grounded answer.</h3><p>Explore invoice counts, categories, and verified amounts from records you have permission to see.</p><div className={styles.questionBubble}>How many invoices need review?<span aria-hidden="true">↗</span></div><div className={styles.insightTags}><span>Counts &amp; status</span><span>Totals by currency</span><span>Source citations</span></div></article>
        </div>
        <div className={styles.pageIntro}><h3>Six connected spaces. One place to sign in.</h3><p>Available actions follow your approved role and invoice access. A guide inside the workspace explains every page.</p></div>
        <div className={styles.pageGrid}>{pages.map(([number, title, description]) => <div key={title}><span>{number}</span><h4>{title}{title === "Admin" && <small>ADMIN ONLY</small>}</h4><p>{description}</p></div>)}</div>
      </section>

      <section className={styles.faqSection} aria-labelledby="faq-title"><div className={`${styles.container} ${styles.faqInner}`}><div><p className={styles.eyebrow}>BEFORE YOU START</p><h2 id="faq-title">A little clarity<br />up front.</h2><p>Getting your team into the right workspace should be straightforward.</p></div><div className={styles.faqList}>{faqs.map(([question, answer]) => <details key={question}><summary>{question}<span aria-hidden="true">+</span></summary><p>{answer}</p></details>)}</div></div></section>
      <section className={`${styles.container} ${styles.finalCta}`} aria-labelledby="start-title"><span className={styles.ctaMark}><Icon name="layers" /></span><p className={styles.eyebrow}>YOUR NEXT CHAPTER, ORGANIZED</p><h2 id="start-title">Give your invoices<br />a clearer way forward.</h2><p>Start with your organization. Build the flow together.</p><div className={styles.heroActions}><a href="#workspace" className={styles.button}>Find your place <Icon name="arrow" /></a><Link href="/login" className={styles.textButton}>Sign in to your workspace <span aria-hidden="true">→</span></Link></div></section>
    </main>
    <footer className={styles.footer}><div className={styles.container}><PublicBrand light className={`${styles.brand} ${styles.brandLight}`} /><p>Documents in. Clear decisions out.</p><nav aria-label="Footer navigation"><a href="#workspace">Get started</a><Link href="/login">Sign in</Link><a href="#workflow">How it works</a></nav></div></footer>
  </div>;
}
