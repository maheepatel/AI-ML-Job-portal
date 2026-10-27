import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type JobDetail } from "../api";
import { JobDetailView } from "../components/JobDetailView";
import { Skeletons } from "../components/ui";

export default function JobPage() {
  const { id } = useParams();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setJob(null);
    api.job(id).then((j) => {
      setJob(j);
      document.title = `${j.title} at ${j.company} — Gradient`;
    }).catch((e) => setError(e.message));
  }, [id]);

  return (
    <div className="container" style={{ maxWidth: 860, padding: "32px 16px 96px" }}>
      <Link to="/jobs" className="caption">← All jobs</Link>
      <div style={{ marginTop: 16 }}>
        {error ? <div className="empty">{error}</div> : job ? <JobDetailView job={job} /> : <Skeletons n={4} />}
      </div>
    </div>
  );
}
