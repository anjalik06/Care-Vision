import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Chart from 'chart.js/auto';

const API = import.meta.env.VITE_API_URL || 'http://localhost:5000/api';
const emotionKeys = ['happy', 'sad', 'angry', 'fear', 'surprise', 'disgust', 'neutral'];
const emotionColors = {
  happy: '#22c55e',
  sad: '#3b82f6',
  angry: '#ef4444',
  fear: '#f59e0b',
  surprise: '#a855f7',
  disgust: '#ec4899',
  neutral: '#94a3b8',
};

function formatTime(value) {
  return value ? new Date(value).toLocaleString() : '--';
}

function formatTimeShort(value) {
  return value ? new Date(value).toLocaleTimeString() : '--';
}

function EmotionBadge({ emotion }) {
  if (!emotion) return <span className="badge badge-neutral">N/A</span>;
  return <span className={`badge badge-${emotion}`}>{emotion.toUpperCase()}</span>;
}

function EmptyState({ icon, children, dark }) {
  return (
    <div className="empty-state" style={dark ? { color: 'white', padding: '80px 20px' } : undefined}>
      {icon && <div className="icon">{icon}</div>}
      <p>{children}</p>
    </div>
  );
}

function ChartCanvas({ config }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !config) return undefined;
    chartRef.current?.destroy();
    chartRef.current = new Chart(canvasRef.current, config);
    return () => chartRef.current?.destroy();
  }, [config]);

  return <canvas ref={canvasRef} />;
}

function App() {
  const [page, setPage] = useState('dashboard');
  const [patients, setPatients] = useState([]);
  const [stats, setStats] = useState(null);
  const [toast, setToast] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [monitorPatientId, setMonitorPatientId] = useState('');
  const [activeMonitorTarget, setActiveMonitorTarget] = useState(null);
  const [latestEmotion, setLatestEmotion] = useState(null);
  const [liveRecords, setLiveRecords] = useState([]);
  const [feedError, setFeedError] = useState(false);
  const [historyPatientId, setHistoryPatientId] = useState('');
  const [historyRecords, setHistoryRecords] = useState([]);
  const [medicationPatientId, setMedicationPatientId] = useState('');
  const [medicationReminders, setMedicationReminders] = useState([]);
  const [medicationForm, setMedicationForm] = useState({ message: '', reminder_time: '09:00', enabled: true });
  const [newPatient, setNewPatient] = useState({
    patient_id: '',
    name: '',
    room: '',
    condition: '',
    caretaker_phone: '',
    feed_port: '5001',
    photo: null,
  });

  const showToast = useCallback((message) => {
    setToast(message);
    window.setTimeout(() => setToast(''), 3000);
  }, []);

  const showMedicationNotification = useCallback((title, body) => {
    showToast(`${title}: ${body}`);
    if (typeof window === 'undefined' || !("Notification" in window)) return;
    if (Notification.permission === 'granted') {
      new Notification(title, { body });
      return;
    }
    if (Notification.permission !== 'denied') {
      Notification.requestPermission().then((permission) => {
        if (permission === 'granted') {
          new Notification(title, { body });
        }
      }).catch(() => {
        // Ignore browser permission errors.
      });
    }
  }, [showToast]);

  const loadPatients = useCallback(async () => {
    const res = await fetch(`${API}/patients`);
    setPatients(await res.json());
  }, []);

  const refreshDashboard = useCallback(async () => {
    try {
      const [statsRes, patientsRes] = await Promise.all([
        fetch(`${API}/dashboard/stats`),
        fetch(`${API}/patients`),
      ]);
      setStats(await statsRes.json());
      setPatients(await patientsRes.json());
    } catch {
      showToast('Failed to load dashboard data');
    }
  }, [showToast]);

  useEffect(() => {
    refreshDashboard();
    const id = window.setInterval(() => {
      if (page === 'dashboard') refreshDashboard();
    }, 10000);
    return () => window.clearInterval(id);
  }, [page, refreshDashboard]);

  useEffect(() => {
    if (page === 'patients' || page === 'monitor' || page === 'history') {
      loadPatients().catch(() => showToast('Failed to load patients'));
    }
  }, [page, loadPatients, showToast]);

  useEffect(() => {
    if (patients.length && !historyPatientId) {
      setHistoryPatientId(patients[0].patient_id);
    }
    if (patients.length && !medicationPatientId) {
      setMedicationPatientId(patients[0].patient_id);
    }
  }, [patients, historyPatientId, medicationPatientId]);

  const fetchActiveMonitorTarget = useCallback(async () => {
    try {
      const res = await fetch(`${API}/monitor/active-patient`);
      if (!res.ok) return;
      const data = await res.json();
      if (data?.patient_id) {
        setActiveMonitorTarget(data);
      } else {
        setActiveMonitorTarget(null);
      }
    } catch {
      // Keep monitor usable even when status endpoint is temporarily unavailable.
    }
  }, []);

  useEffect(() => {
    async function loadActiveMonitorPatient() {
      try {
        const res = await fetch(`${API}/monitor/active-patient`);
        if (!res.ok) return;
        const data = await res.json();
        if (data?.patient_id) {
          setMonitorPatientId(data.patient_id);
          setActiveMonitorTarget(data);
        }
      } catch {
        // Keep UI working even if monitor endpoint is temporarily unavailable.
      }
    }
    loadActiveMonitorPatient();
  }, []);

  const selectedMonitorPatient = patients.find((p) => p.patient_id === monitorPatientId);
  const videoFeedUrl = monitorPatientId ? `${API}/video_feed/${monitorPatientId}` : '';

  const fetchLatestEmotion = useCallback(async () => {
    if (!monitorPatientId) return;
    try {
      const [latestRes, recentRes] = await Promise.all([
        fetch(`${API}/emotions/${monitorPatientId}/latest`),
        fetch(`${API}/emotions/${monitorPatientId}?minutes=1`),
      ]);
      if (latestRes.ok) setLatestEmotion(await latestRes.json());
      if (recentRes.ok) setLiveRecords(await recentRes.json());
    } catch {
      // The live panel can remain quiet while the FER process warms up.
    }
  }, [monitorPatientId]);

  useEffect(() => {
    fetchActiveMonitorTarget();
    const id = window.setInterval(fetchActiveMonitorTarget, 2000);
    return () => window.clearInterval(id);
  }, [fetchActiveMonitorTarget]);

  useEffect(() => {
    setFeedError(false);
    setLatestEmotion(null);
    setLiveRecords([]);
    if (!monitorPatientId) return undefined;

    fetch(`${API}/monitor/active-patient`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patient_id: monitorPatientId }),
    }).then(() => fetchActiveMonitorTarget()).catch(() => {
      // Selection still updates locally; backend sync can retry on next change.
    });

    fetchLatestEmotion();
    const id = window.setInterval(fetchLatestEmotion, 2000);
    return () => window.clearInterval(id);
  }, [monitorPatientId, fetchLatestEmotion, fetchActiveMonitorTarget]);

  const loadHistory = useCallback(async (patientId = historyPatientId) => {
    if (!patientId) return;
    try {
      const res = await fetch(`${API}/emotions/${patientId}?minutes=1`);
      setHistoryRecords(await res.json());
    } catch {
      showToast('Failed to load history');
    }
  }, [historyPatientId, showToast]);

  useEffect(() => {
    loadHistory();
  }, [historyPatientId, loadHistory]);

  const loadMedicationReminders = useCallback(async (patientId = medicationPatientId) => {
    if (!patientId) {
      setMedicationReminders([]);
      return;
    }
    try {
      const res = await fetch(`${API}/medications/${patientId}`);
      if (!res.ok) throw new Error('Failed');
      setMedicationReminders(await res.json());
    } catch {
      showToast('Failed to load medication reminders');
    }
  }, [medicationPatientId, showToast]);

  useEffect(() => {
    loadMedicationReminders();
  }, [medicationPatientId, loadMedicationReminders]);

  useEffect(() => {
    async function checkDueMedicationNotifications() {
      try {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2, '0');
        const mm = String(now.getMinutes()).padStart(2, '0');
        const date = now.toISOString().slice(0, 10);
        const res = await fetch(`${API}/medications/due?time=${hh}:${mm}&date=${date}`);
        if (!res.ok) return;
        const due = await res.json();
        due.forEach((item) => {
          showMedicationNotification(
            `Medication Reminder - ${item.patient_name || item.patient_id}`,
            item.message || 'Take your medication'
          );
        });
      } catch {
        // Keep UI responsive if notification polling fails.
      }
    }

    checkDueMedicationNotifications();
    const id = window.setInterval(checkDueMedicationNotifications, 30000);
    return () => window.clearInterval(id);
  }, [showMedicationNotification]);

  async function addPatient(event) {
    event.preventDefault();
    if (!newPatient.patient_id || !newPatient.name || !newPatient.caretaker_phone) {
      showToast('Please fill in Patient ID, Name, and Caretaker Mobile Number');
      return;
    }

    try {
      const formData = new FormData();
      Object.entries(newPatient).forEach(([key, value]) => {
        if (value) formData.append(key, value);
      });
      const res = await fetch(`${API}/patients`, { method: 'POST', body: formData });
      const data = await res.json();
      showToast(data.message || data.error || 'Patient saved');
      setModalOpen(false);
      setNewPatient({
        patient_id: '',
        name: '',
        room: '',
        condition: '',
        caretaker_phone: '',
        feed_port: '5001',
        photo: null,
      });
      await loadPatients();
      await refreshDashboard();
    } catch {
      showToast('Failed to add patient');
    }
  }

  async function deletePatient(patientId) {
    if (!window.confirm(`Delete patient ${patientId}? This will also remove all emotion records.`)) return;
    try {
      await fetch(`${API}/patients/${patientId}`, { method: 'DELETE' });
      showToast('Patient deleted');
      await loadPatients();
      await refreshDashboard();
    } catch {
      showToast('Failed to delete patient');
    }
  }

  async function addMedicationReminder(event) {
    event.preventDefault();
    if (!medicationPatientId) {
      showToast('Select a patient first');
      return;
    }
    if (!medicationForm.message.trim()) {
      showToast('Medication message is required');
      return;
    }
    try {
      const res = await fetch(`${API}/medications`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: medicationPatientId,
          message: medicationForm.message.trim(),
          reminder_time: medicationForm.reminder_time,
          enabled: medicationForm.enabled,
        }),
      });
      if (!res.ok) throw new Error('Failed');
      setMedicationForm({ message: '', reminder_time: medicationForm.reminder_time, enabled: true });
      showToast('Medication reminder added');
      await loadMedicationReminders(medicationPatientId);
    } catch {
      showToast('Failed to add medication reminder');
    }
  }

  async function toggleMedicationReminder(reminder) {
    try {
      const res = await fetch(`${API}/medications/${reminder.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !reminder.enabled }),
      });
      if (!res.ok) throw new Error('Failed');
      await loadMedicationReminders(reminder.patient_id);
    } catch {
      showToast('Failed to update reminder');
    }
  }

  async function deleteMedicationReminder(reminder) {
    try {
      const res = await fetch(`${API}/medications/${reminder.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed');
      showToast('Reminder deleted');
      await loadMedicationReminders(reminder.patient_id);
    } catch {
      showToast('Failed to delete reminder');
    }
  }

  async function sendInstantMedicationReminder(reminder) {
    try {
      const res = await fetch(`${API}/medications/${reminder.id}/send-now`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      const payload = await res.json();
      showMedicationNotification(
        `Medication Reminder - ${payload.patient_name || payload.patient_id}`,
        payload.message || 'Take your medication'
      );
    } catch {
      showToast('Failed to send instant reminder');
    }
  }

  const pieConfig = useMemo(() => {
    const dist = stats?.emotion_distribution || {};
    const labels = Object.keys(dist);
    return {
      type: 'doughnut',
      data: {
        labels: labels.map((label) => label.charAt(0).toUpperCase() + label.slice(1)),
        datasets: [{
          data: Object.values(dist),
          backgroundColor: labels.map((label) => emotionColors[label] || emotionColors.neutral),
          borderWidth: 2,
          borderColor: '#fff',
        }],
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } },
    };
  }, [stats]);

  const liveChartConfig = useMemo(() => {
    const emotions = latestEmotion?.emotions;
    if (!emotions) return null;
    const labels = Object.keys(emotions);
    return {
      type: 'bar',
      data: {
        labels: labels.map((label) => label.charAt(0).toUpperCase() + label.slice(1)),
        datasets: [{
          data: Object.values(emotions),
          backgroundColor: labels.map((label) => emotionColors[label] || emotionColors.neutral),
          borderRadius: 6,
          borderSkipped: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, max: 100, ticks: { callback: (v) => `${v}%` } }, x: { grid: { display: false } } },
      },
    };
  }, [latestEmotion]);

  const historyLineConfig = useMemo(() => ({
    type: 'line',
    data: {
      labels: historyRecords.map((record) => formatTimeShort(record.timestamp)),
      datasets: emotionKeys.map((emotion) => ({
        label: emotion.charAt(0).toUpperCase() + emotion.slice(1),
        data: historyRecords.map((record) => record.emotions?.[emotion] || 0),
        borderColor: emotionColors[emotion],
        backgroundColor: `${emotionColors[emotion]}20`,
        tension: 0.3,
        borderWidth: 2,
        pointRadius: 0,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: { y: { beginAtZero: true, max: 100, ticks: { callback: (v) => `${v}%` } } },
      interaction: { mode: 'index', intersect: false },
    },
  }), [historyRecords]);

  const historyBarConfig = useMemo(() => {
    const averages = emotionKeys.map((emotion) => {
      const values = historyRecords.map((record) => record.emotions?.[emotion] || 0);
      return values.reduce((sum, value) => sum + value, 0) / (values.length || 1);
    });
    return {
      type: 'bar',
      data: {
        labels: emotionKeys.map((emotion) => emotion.charAt(0).toUpperCase() + emotion.slice(1)),
        datasets: [{ data: averages, backgroundColor: emotionKeys.map((emotion) => emotionColors[emotion]), borderRadius: 6 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: (v) => `${Number(v).toFixed(0)}%` } }, x: { grid: { display: false } } },
      },
    };
  }, [historyRecords]);

  const alerts = stats?.alerts || [];

  return (
    <>
      <nav className="sidebar">
        <div className="sidebar-header">
          <h1><span className="logo">&#9829;</span> Care Vision</h1>
          <p>Patient Monitoring</p>
        </div>
        <div className="sidebar-nav">
          {[
            ['dashboard', '&#9632;', 'Dashboard'],
            ['patients', '&#9834;', 'Patients'],
            ['monitor', '&#9673;', 'Live Monitor'],
            ['history', '&#9776;', 'History'],
            ['medication', '&#9200;', 'Medication'],
          ].map(([key, icon, label]) => (
            <button key={key} className={page === key ? 'active nav-button' : 'nav-button'} onClick={() => setPage(key)}>
              <span className="icon" dangerouslySetInnerHTML={{ __html: icon }} /> {label}
            </button>
          ))}
        </div>
        <div className="sidebar-footer">Care Vision v1.0<br />Facial Emotion Recognition</div>
      </nav>

      <div className="toast-container">{toast && <div className="toast">{toast}</div>}</div>

      {modalOpen && (
        <div className="modal-overlay active">
          <form className="modal" onSubmit={addPatient}>
            <h3>Add New Patient</h3>
            {[
              ['patient_id', 'Patient ID', 'e.g., patient_002'],
              ['name', 'Full Name', 'e.g., John Smith'],
              ['room', 'Room / Location', 'e.g., Room 204, Ward B'],
              ['condition', 'Condition / Notes', 'e.g., Post-surgery recovery'],
              ['caretaker_phone', 'Caretaker Mobile Number', 'e.g., +919876543210'],
              ['feed_port', 'Video Feed Port', '5001'],
            ].map(([key, label, placeholder]) => (
              <div className="form-group" key={key}>
                <label>{label}</label>
                <input
                  type={key === 'feed_port' ? 'number' : key === 'caretaker_phone' ? 'tel' : 'text'}
                  value={newPatient[key]}
                  placeholder={placeholder}
                  required={['patient_id', 'name', 'caretaker_phone'].includes(key)}
                  onChange={(event) => setNewPatient((current) => ({ ...current, [key]: event.target.value }))}
                />
              </div>
            ))}
            <div className="form-group">
              <label>Patient Face Photo</label>
              <input type="file" accept="image/*" onChange={(event) => setNewPatient((current) => ({ ...current, photo: event.target.files[0] }))} />
            </div>
            <div className="modal-actions">
              <button className="btn" type="button" onClick={() => setModalOpen(false)}>Cancel</button>
              <button className="btn btn-primary" type="submit">Add Patient</button>
            </div>
          </form>
        </div>
      )}

      <main className="main">
        {page === 'dashboard' && (
          <section>
            <div className="page-header">
              <div><h2>Dashboard</h2><p className="subtitle">Real-time patient emotion overview</p></div>
              <button className="btn btn-primary" onClick={refreshDashboard}>&#8635; Refresh</button>
            </div>
            <div className="stats-grid">
              <Stat icon="&#128100;" tone="blue" value={stats?.total_patients || 0} label="Total Patients" />
              <Stat icon="&#128200;" tone="green" value={stats?.total_records || 0} label="Emotion Records" />
              <Stat icon="&#128337;" tone="orange" value={stats?.recent_count || 0} label="Last 1 min Records" />
              <Stat icon="&#9888;" tone="red" value={alerts.length} label="Active Alerts" />
            </div>
            <div className="grid-3">
              <div className="card"><div className="card-header">Emotion Distribution (Last 1 min)</div><div className="card-body"><div className="chart-container"><ChartCanvas config={pieConfig} /></div></div></div>
              <div className="card">
                <div className="card-header">Alerts <span className="badge badge-angry">{alerts.length}</span></div>
                <div className="card-body">
                  {alerts.length ? alerts.map((alert) => (
                    <div className="alert-item" key={`${alert.patient_id}-${alert.timestamp}`}>
                      <div className="alert-dot" />
                      <div className="alert-info"><strong>{alert.name}</strong> ({alert.room || 'No room'})<p>Detected: {alert.emotion.toUpperCase()} at {formatTime(alert.timestamp)}</p></div>
                    </div>
                  )) : <EmptyState icon="&#10003;">No active alerts. All patients are stable.</EmptyState>}
                </div>
              </div>
            </div>
            <PatientTable patients={patients} />
          </section>
        )}

        {page === 'patients' && (
          <section>
            <div className="page-header">
              <div><h2>Patients</h2><p className="subtitle">Manage registered patients</p></div>
              <button className="btn btn-primary" onClick={() => setModalOpen(true)}>+ Add Patient</button>
            </div>
            <div className="patient-grid">
              {patients.length ? patients.map((patient) => (
                <div className="patient-card" key={patient.patient_id} onClick={() => { setPage('monitor'); setMonitorPatientId(patient.patient_id); }}>
                  <div className="patient-card-header"><div><h4>{patient.name}</h4><div className="patient-id">{patient.patient_id}</div></div><EmotionBadge emotion={patient.latest_emotion} /></div>
                  <div className="patient-meta"><span>&#128205; {patient.room || 'No room'}</span><span>&#128247; Port {patient.feed_port}</span><span>{patient.has_photo ? 'Face registered' : 'No face photo'}</span></div>
                  <div className="patient-meta">Alert: {patient.caretaker_phone || 'No caretaker mobile'}</div>
                  {patient.condition && <div className="patient-meta">{patient.condition}</div>}
                  <div className="patient-actions"><span>Added: {formatTime(patient.created_at)}</span><button className="btn btn-danger btn-sm" onClick={(event) => { event.stopPropagation(); deletePatient(patient.patient_id); }}>Delete</button></div>
                </div>
              )) : <EmptyState icon="&#128100;">No patients registered. Click Add Patient to get started.</EmptyState>}
            </div>
          </section>
        )}

        {page === 'monitor' && (
          <section>
            <div className="page-header">
              <div><h2>Live Monitor</h2><p className="subtitle">Real-time video feed with emotion detection</p></div>
              <select className="btn select-control" value={monitorPatientId} onChange={(event) => setMonitorPatientId(event.target.value)}>
                <option value="">Select a patient...</option>
                {patients.map((patient) => <option key={patient.patient_id} value={patient.patient_id}>{patient.name} ({patient.patient_id})</option>)}
              </select>
            </div>
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-body" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                  <strong>Active FER Target:</strong>{' '}
                  {activeMonitorTarget?.name
                    ? `${activeMonitorTarget.name} (${activeMonitorTarget.patient_id})`
                    : (activeMonitorTarget?.patient_id || '--')}
                </div>
                {monitorPatientId && (
                  <span className={`badge ${activeMonitorTarget?.patient_id === monitorPatientId ? 'badge-happy' : 'badge-fear'}`}>
                    {activeMonitorTarget?.patient_id === monitorPatientId ? 'Synced' : 'Switching...'}
                  </span>
                )}
              </div>
            </div>
            <div className="grid-2">
              <div className="card">
                <div className="card-header">Video Feed {selectedMonitorPatient && <span className="badge badge-neutral">Port {selectedMonitorPatient.feed_port}</span>}</div>
                <div className="card-body">
                  <div className="live-feed-container">
                    {!monitorPatientId && <EmptyState icon="&#128249;" dark>Select a patient to view live feed</EmptyState>}
                    {monitorPatientId && feedError && <EmptyState icon="&#9888;" dark>Could not connect to the FER service. Make sure it is running.</EmptyState>}
                    {monitorPatientId && !feedError && <img src={videoFeedUrl} alt="Live Feed" onError={() => setFeedError(true)} />}
                    {monitorPatientId && !feedError && <div className="live-badge"><span className="dot" /> LIVE</div>}
                  </div>
                </div>
              </div>
              <div className="card">
                <div className="card-header">Current Emotions</div>
                <div className="card-body">
                  <div className="chart-container">{liveChartConfig ? <ChartCanvas config={liveChartConfig} /> : <EmptyState>No emotion data yet</EmptyState>}</div>
                  <div className="dominant-emotion"><p>Dominant Emotion</p><h3>{latestEmotion?.dominant_emotion?.toUpperCase() || '--'}</h3></div>
                </div>
              </div>
            </div>
            <div className="card">
              <div className="card-header">Recent Emotions Timeline</div>
              <div className="card-body emotion-timeline">
                {liveRecords.length ? [...liveRecords].reverse().map((record) => (
                  <div className="timeline-item" key={`${record.timestamp}-${record.dominant_emotion}`}><span className="timeline-time">{formatTimeShort(record.timestamp)}</span><EmotionBadge emotion={record.dominant_emotion} /></div>
                )) : <EmptyState>Emotion data will appear here</EmptyState>}
              </div>
            </div>
          </section>
        )}

        {page === 'history' && (
          <section>
            <div className="page-header">
              <div><h2>Emotion History</h2><p className="subtitle">Historical emotion data and trends</p></div>
              <select className="btn select-control" value={historyPatientId} onChange={(event) => setHistoryPatientId(event.target.value)}>
                <option value="">Select a patient...</option>
                {patients.map((patient) => <option key={patient.patient_id} value={patient.patient_id}>{patient.name} ({patient.patient_id})</option>)}
              </select>
            </div>
            <div className="grid-2">
              <div className="card"><div className="card-header">Emotion Over Time (Last 1 min)</div><div className="card-body"><div className="chart-container"><ChartCanvas config={historyLineConfig} /></div></div></div>
              <div className="card"><div className="card-header">Emotion Breakdown</div><div className="card-body"><div className="chart-container"><ChartCanvas config={historyBarConfig} /></div></div></div>
            </div>
            <div className="card">
              <div className="card-header">Emotion Log <span className="badge badge-neutral">{historyRecords.length} records</span></div>
              <div className="card-body table-scroll"><HistoryTable records={historyRecords} /></div>
            </div>
          </section>
        )}

        {page === 'medication' && (
          <section>
            <div className="page-header">
              <div><h2>Medication Notifications</h2><p className="subtitle">Set daily reminders per patient and send instant notifications</p></div>
              <select className="btn select-control" value={medicationPatientId} onChange={(event) => setMedicationPatientId(event.target.value)}>
                <option value="">Select a patient...</option>
                {patients.map((patient) => <option key={patient.patient_id} value={patient.patient_id}>{patient.name} ({patient.patient_id})</option>)}
              </select>
            </div>

            <div className="grid-2">
              <div className="card">
                <div className="card-header">Add Daily Reminder</div>
                <div className="card-body">
                  <form onSubmit={addMedicationReminder}>
                    <div className="form-group">
                      <label>Reminder Message</label>
                      <input
                        type="text"
                        placeholder="e.g., Take your medication"
                        value={medicationForm.message}
                        onChange={(event) => setMedicationForm((current) => ({ ...current, message: event.target.value }))}
                        required
                      />
                    </div>
                    <div className="form-group">
                      <label>Time (Daily)</label>
                      <input
                        type="time"
                        value={medicationForm.reminder_time}
                        onChange={(event) => setMedicationForm((current) => ({ ...current, reminder_time: event.target.value }))}
                        required
                      />
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <input
                        id="enabled-new-reminder"
                        type="checkbox"
                        checked={medicationForm.enabled}
                        onChange={(event) => setMedicationForm((current) => ({ ...current, enabled: event.target.checked }))}
                        style={{ width: 16, height: 16 }}
                      />
                      <label htmlFor="enabled-new-reminder" style={{ marginBottom: 0 }}>Enabled</label>
                    </div>
                    <button className="btn btn-primary" type="submit">Add Reminder</button>
                  </form>
                </div>
              </div>

              <div className="card">
                <div className="card-header">Patient Reminders</div>
                <div className="card-body table-scroll">
                  {!medicationPatientId && <EmptyState>Select a patient to manage reminders</EmptyState>}
                  {medicationPatientId && !medicationReminders.length && <EmptyState>No medication reminders set yet</EmptyState>}
                  {medicationPatientId && medicationReminders.length > 0 && (
                    <table>
                      <thead><tr><th>Time</th><th>Message</th><th>Status</th><th>Actions</th></tr></thead>
                      <tbody>
                        {medicationReminders.map((reminder) => (
                          <tr key={reminder.id}>
                            <td><strong>{reminder.reminder_time}</strong></td>
                            <td>{reminder.message}</td>
                            <td><span className={`badge ${reminder.enabled ? 'badge-happy' : 'badge-neutral'}`}>{reminder.enabled ? 'Enabled' : 'Disabled'}</span></td>
                            <td style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                              <button className="btn btn-primary btn-sm" type="button" onClick={() => sendInstantMedicationReminder(reminder)}>Send Now</button>
                              <button className="btn btn-sm" type="button" onClick={() => toggleMedicationReminder(reminder)}>{reminder.enabled ? 'Disable' : 'Enable'}</button>
                              <button className="btn btn-danger btn-sm" type="button" onClick={() => deleteMedicationReminder(reminder)}>Delete</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          </section>
        )}
      </main>
    </>
  );
}

function Stat({ icon, tone, value, label }) {
  return (
    <div className="stat-card">
      <div className={`stat-icon ${tone}`} dangerouslySetInnerHTML={{ __html: icon }} />
      <div className="stat-info"><h3>{value}</h3><p>{label}</p></div>
    </div>
  );
}

function PatientTable({ patients }) {
  return (
    <div className="card">
      <div className="card-header">Patient Overview</div>
      <div className="card-body table-scroll">
        <table>
          <thead><tr><th>Patient</th><th>ID</th><th>Room</th><th>Current Emotion</th><th>Last Updated</th></tr></thead>
          <tbody>
            {patients.length ? patients.map((patient) => (
              <tr key={patient.patient_id}><td><strong>{patient.name}</strong></td><td>{patient.patient_id}</td><td>{patient.room || '--'}</td><td><EmotionBadge emotion={patient.latest_emotion} /></td><td>{formatTime(patient.latest_timestamp)}</td></tr>
            )) : <tr><td colSpan="5"><EmptyState>No patients registered yet</EmptyState></td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HistoryTable({ records }) {
  return (
    <table>
      <thead><tr><th>Timestamp</th><th>Dominant Emotion</th><th>Happy</th><th>Sad</th><th>Angry</th><th>Fear</th><th>Surprise</th><th>Neutral</th></tr></thead>
      <tbody>
        {[...records].reverse().slice(0, 50).map((record) => {
          const emotions = record.emotions || {};
          return (
            <tr key={`${record.timestamp}-${record.dominant_emotion}`}>
              <td>{formatTime(record.timestamp)}</td><td><EmotionBadge emotion={record.dominant_emotion} /></td>
              <td>{(emotions.happy || 0).toFixed(1)}%</td><td>{(emotions.sad || 0).toFixed(1)}%</td><td>{(emotions.angry || 0).toFixed(1)}%</td><td>{(emotions.fear || 0).toFixed(1)}%</td><td>{(emotions.surprise || 0).toFixed(1)}%</td><td>{(emotions.neutral || 0).toFixed(1)}%</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default App;
