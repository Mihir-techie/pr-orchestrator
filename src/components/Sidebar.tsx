import { GitPullRequest, LayoutDashboard, Settings2, Workflow } from "lucide-react";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="PR Orchestrator home">
        <span className="brand-mark">
          <Workflow size={21} strokeWidth={2.3} />
        </span>
        <span>
          <strong>mergeflow</strong>
          <small>PR ORCHESTRATOR</small>
        </span>
      </a>

      <div className="nav-caption">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        <a className="nav-item active" href="#overview" aria-current="page">
          <LayoutDashboard size={18} />
          Overview
          <span className="nav-active-dot" />
        </a>
        <a className="nav-item" href="#reviews">
          <GitPullRequest size={18} />
          Pull requests
        </a>
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <span className="note-icon">
            <Workflow size={17} />
          </span>
          <strong>
            Smart reviews,
            <br />
            <span>thoughtful routing.</span>
          </strong>
          <p>Every pull request gets the right model for the job.</p>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">PF</span>
          <span className="profile-copy">
            <strong>PR Workspace</strong>
            <small>Personal dashboard</small>
          </span>
          <Settings2 size={17} className="footer-settings" />
        </div>
      </div>
    </aside>
  );
}
