import { useEffect, useRef, useState } from 'react';
import { HttpApiError, getLatestEnvelope, listPatients, sendChat } from '../api';
import type { Patient, ChatMessageResponse, Citation, Envelope } from '../types';
import LoadingState from '../components/LoadingState';
import PageHeader from '../components/PageHeader';
import { useRequestScope } from '../hooks/useRequestScope';
import { useDemo } from '../demo/context';
import { useSharedPatient } from '../demo/useSharedPatient';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  escalated?: boolean;
  citations?: Citation[];
}

const EXAMPLE_QUESTIONS = [
  'Why is my sodium limit 2000?',
  'Which foods should I avoid?',
  'Why is my protein target a range?',
];

export default function ChatScreen() {
  const demo = useDemo();
  const isPatientView = demo.view === 'patient';
  const requests = useRequestScope();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [envelopeStatus, setEnvelopeStatus] = useState<Envelope['status'] | 'NONE' | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const selectPatient = (patient: Patient | null) => {
    requests.reset();
    demo.setPatientId(patient?.id || null);
    setSelectedPatient(patient);
    setEnvelopeStatus(null);
    setMessages([]);
    setInput('');
    setError(null);
    setSending(false);
    if (patient && getLatestEnvelope) {
      const isCurrent = requests.start('envelope');
      Promise.resolve(getLatestEnvelope(patient.id))
        .then((env) => { if (isCurrent() && env) setEnvelopeStatus(env.status); })
        .catch((err) => {
          if (isCurrent() && err instanceof HttpApiError && err.code === 'envelope_not_found') {
            setEnvelopeStatus('NONE');
          }
        });
    }
  };

  useSharedPatient(patients, selectedPatient?.id, selectPatient);

  const submitQuestion = async (question: string) => {
    const trimmed = question.trim();
    if (!selectedPatient || !trimmed || sending) return;
    const isCurrent = requests.start('chat');

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      text: trimmed,
    };

    setMessages((prev) => [...prev, userMsg]);
    setSending(true);
    setError(null);
    setInput('');

    try {
      const result: ChatMessageResponse = await sendChat(selectedPatient.id, trimmed);
      if (!isCurrent()) return;
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: result.answer,
        escalated: result.escalated,
        citations: result.citations,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to send message');
    } finally {
      if (isCurrent()) setSending(false);
    }
  };

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    void submitQuestion(input);
  };

  return (
    <main className="pb-12">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
        <PageHeader code="CHT" title={isPatientView ? 'Ask about your diet' : 'Chat'}>
          {isPatientView
            ? 'Ask questions about your nutrition targets. Answers cite the clinical guidelines behind your plan.'
            : 'Ask questions about a patient’s diet plan (previewing the patient assistant). Citations link back to guidelines.'}
        </PageHeader>

        {!isPatientView ? (
          <div className="panel mb-4 p-4">
            <label htmlFor="chat-patient" className="micro-label mb-1 block">
              Patient
            </label>
            {loadingPatients ? (
              <LoadingState text="Loading patients…" />
            ) : (
              <select
                id="chat-patient"
                value={selectedPatient?.id || ''}
                onChange={(e) => {
                  const p = patients.find((pt) => pt.id === e.target.value) || null;
                  selectPatient(p);
                }}
                className="field"
              >
                <option value="">Select a patient</option>
                {patients.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name || p.id} — {p.diagnoses?.join(', ')}
                  </option>
                ))}
              </select>
            )}
          </div>
        ) : (
          <div className="panel mb-4 flex flex-wrap items-center justify-between gap-2 p-4 text-sm text-ink-2">
            <span>
              {selectedPatient
                ? <>Asking as <span className="font-semibold text-ink">{selectedPatient.name || selectedPatient.id}</span>.</>
                : 'Choose a patient in the Acting as bar above to ask a question.'}
            </span>
            {envelopeStatus && <EnvelopeContextBadge status={envelopeStatus} />}
          </div>
        )}

        {!isPatientView && selectedPatient && envelopeStatus && (
          <div className="mb-4">
            <EnvelopeContextBadge status={envelopeStatus} />
          </div>
        )}

        {error && (
          <div className="notice notice-error mb-4">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-semibold underline">
              Dismiss
            </button>
          </div>
        )}

        <div className="panel">
          <div className="flex h-96 flex-col">
            <div className="flex-1 overflow-y-auto p-4">
              {messages.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                  <p className="text-sm text-ink-3">
                    {selectedPatient
                      ? 'Type a question below or pick an example to begin.'
                      : 'Select a patient and type a message to begin.'}
                  </p>
                  {selectedPatient && (
                    <div className="flex flex-wrap justify-center gap-2">
                      {EXAMPLE_QUESTIONS.map((q) => (
                        <button
                          key={q}
                          type="button"
                          disabled={sending}
                          onClick={() => void submitQuestion(q)}
                          className="btn-ghost min-h-0 px-3 py-1.5 text-xs"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-2xl border px-4 py-3 text-sm ${
                          msg.role === 'user'
                            ? 'border-ink bg-ink text-paper'
                            : 'border-rule bg-card text-ink'
                        }`}
                      >
                        <p className="micro-label mb-1.5" style={{ color: msg.role === 'user' ? 'var(--color-rule-2)' : undefined }}>
                          {msg.role === 'user' ? 'Query' : 'Response'}
                        </p>
                        <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                        {msg.role === 'assistant' && msg.escalated && (
                          <div className="notice notice-warn mt-3 flex items-start gap-2">
                            <svg className="mt-0.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 3.5V2m0 0a2.5 2.5 0 012.5 2.5v.5M21 9.5h-2.5m-4.5 0H9m-4.5 0H2m3 0v7.2a2 2 0 00.8 1.6l1.7 1.3a2 2 0 002.4 0l1.7-1.3a2 2 0 01.8-.2h4.6a2 2 0 01.8.2l1.7 1.3a2 2 0 002.4 0l1.7-1.3a2 2 0 00.8-1.6V9.5" />
                            </svg>
                            <span className="font-medium">Contact your clinician about this question.</span>
                          </div>
                        )}
                        {msg.role === 'assistant' && msg.citations && msg.citations.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-rule pt-2.5">
                            {msg.citations.map((c, idx) => (
                              <a
                                key={idx}
                                href={c.url ?? undefined}
                                target="_blank"
                                rel="noreferrer"
                                className="flag flag-info hover:underline"
                              >
                                {c.guideline}
                                <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m-6-6L10 14" />
                                </svg>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>

            <form onSubmit={handleSend} className="border-t border-rule-2 p-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={selectedPatient ? 'Type your question…' : 'Select a patient first'}
                  disabled={!selectedPatient || sending}
                  className="field flex-1"
                />
                <button
                  type="submit"
                  disabled={!selectedPatient || sending || !input.trim()}
                  className="btn-primary"
                >
                  {sending ? 'Sending…' : 'Send'}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </main>
  );
}

function EnvelopeContextBadge({ status }: { status: Envelope['status'] | 'NONE' }) {
  if (status === 'APPROVED') {
    return <span className="flag flag-ok">Targets approved — personal numbers enabled</span>;
  }
  if (status === 'REJECTED') {
    return <span className="flag flag-bad">Targets rejected — personal guidance unavailable</span>;
  }
  if (status === 'NONE') {
    return <span className="flag flag-warn">No envelope yet — general guideline answers only</span>;
  }
  return <span className="flag flag-warn">Targets {status} — pending review, personal numbers withheld</span>;
}
