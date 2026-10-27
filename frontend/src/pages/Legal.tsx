const CONTACT = import.meta.env.VITE_CONTACT_EMAIL as string | undefined;

export function ContactLine() {
  return CONTACT ? (
    <>Questions, corrections or takedown requests: <a href={`mailto:${CONTACT}`} style={{ textDecoration: "underline" }}>{CONTACT}</a>.</>
  ) : (
    <>Questions, corrections or takedown requests: use the contact link in the site footer.</>
  );
}

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="container" style={{ maxWidth: 760, padding: "48px 16px 96px", fontWeight: 400 }}>
      <h1 style={{ fontSize: 48, marginBottom: 8 }}>{title}</h1>
      <p className="caption">Last updated 22 October 2026</p>
      {children}
    </div>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy">
      <h3>What we collect</h3>
      <p>Gradient has no accounts and sets no tracking cookies. Our servers keep standard request logs (IP address, URL, time) for up to 14 days to keep the service secure and rate-limited.</p>
      <h3>Résumé uploads</h3>
      <p>When you upload a résumé on “For me”, the PDF is read in memory to extract skills and experience, used to rank jobs for that one request, and then discarded. It is never written to disk or a database, and is not shared with anyone. Email addresses and phone numbers are stripped before matching.</p>
      <h3>Job data</h3>
      <p>Job listings are public postings collected from employer career systems, LinkedIn's public job pages and public job boards. If you are an employer and want a listing corrected or removed, contact us and we will act on it promptly.</p>
      <h3>Contact</h3>
      <p><ContactLine /></p>
    </Page>
  );
}

export function Terms() {
  return (
    <Page title="Terms">
      <h3>The service</h3>
      <p>Gradient indexes publicly posted AI/ML job openings and links to the original posting. We do not employ, recruit for, or represent any listed company. Always apply on the employer's own site.</p>
      <h3>No guarantees</h3>
      <p>Listings, trust scores and match scores are produced automatically and can be wrong or out of date. A “verified” badge means the role was found on the employer's own system, not that we vouch for it. Never pay anyone to apply for a job.</p>
      <h3>Fair use</h3>
      <p>Don't scrape or overload the site or API; requests are rate-limited. Listing content belongs to the respective employers and sources.</p>
      <h3>Contact</h3>
      <p><ContactLine /></p>
    </Page>
  );
}
