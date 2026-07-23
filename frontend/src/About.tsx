import { useEffect } from 'react'

export function AboutPage() {
  useEffect(() => {
    const previousTitle = document.title
    document.title = 'About · Stock Monitor'
    return () => { document.title = previousTitle }
  }, [])

  return <div className="about-page">
    <header className="about-nav">
      <a className="about-brand" href="/" aria-label="Stock Monitor dashboard">
        <span aria-hidden="true">SM</span>
        <strong>Stock Monitor</strong>
      </a>
      <a className="about-dashboard-link" href="/">Dashboard <span aria-hidden="true">→</span></a>
    </header>

    <main className="about-main">
      <section className="about-hero" aria-labelledby="about-title">
        <p className="about-eyebrow">About this project</p>
        <h1 id="about-title">Stock Monitor</h1>
        <p>A personal, non-commercial investment research dashboard.</p>
      </section>

      <div className="about-sections">
        <section className="about-card about-card-wide">
          <p className="about-section-number" aria-hidden="true">01</p>
          <div>
            <h2>What is Stock Monitor?</h2>
            <p>Stock Monitor is a personal investment research dashboard developed for personal use. It helps monitor stocks by bringing several kinds of research material into one place:</p>
            <ul className="about-source-list">
              <li>Market data</li>
              <li>Financial statements</li>
              <li>Technical indicators</li>
              <li>Valuation analysis</li>
              <li>News aggregation</li>
              <li>Public community discussions</li>
            </ul>
          </div>
        </section>

        <section className="about-card about-card-wide">
          <p className="about-section-number" aria-hidden="true">02</p>
          <div>
            <h2>Reddit Integration</h2>
            <p>Reddit is accessed in read-only mode through the official Reddit Data API. Reddit content is used only to:</p>
            <ul>
              <li>Measure discussion volume</li>
              <li>Analyze general market sentiment</li>
              <li>Identify notable investment-related topics</li>
              <li>Generate aggregated insights for a personal watchlist</li>
            </ul>
            <div className="about-policy" aria-label="Reddit actions the application does not perform">
              <h3>The application does not</h3>
              <ul>
                <li>Post to Reddit or vote</li>
                <li>Send private messages</li>
                <li>Automate Reddit accounts</li>
                <li>Scrape Reddit outside the official API</li>
                <li>Resell Reddit content</li>
                <li>Use Reddit content to train AI models</li>
              </ul>
            </div>
          </div>
        </section>

        <section className="about-card">
          <p className="about-section-number" aria-hidden="true">03</p>
          <div>
            <h2>Data Usage</h2>
            <p>Only publicly available Reddit content retrieved through Reddit's official API is processed. The data is used solely for personal investment research and sentiment analysis.</p>
          </div>
        </section>

        <section className="about-card">
          <p className="about-section-number" aria-hidden="true">04</p>
          <div>
            <h2>Current Status</h2>
            <p>This is currently a personal, non-commercial project. If commercial use of Reddit data is introduced in the future, appropriate permissions will be obtained and applicable Reddit policies will be followed.</p>
          </div>
        </section>

        <section className="about-card about-contact">
          <p className="about-section-number" aria-hidden="true">05</p>
          <div>
            <h2>Contact</h2>
            <p>Project source and technical details are available in the public repository.Email:jiale@jialenb.com</p>
          </div>
        </section>
      </div>
    </main>

    <footer className="about-footer">
      <span>Stock Monitor</span>
      <span>Personal research project</span>
    </footer>
  </div>
}
