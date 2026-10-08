import { useEffect, useRef, useState } from 'react';
import { listPatients, sendChat } from '../api';
import type { Patient, ChatMessageResponse, Citation } from '../types';
import LoadingState from '../components/LoadingState';
import { useRequestScope } from '../hooks/useRequestScope';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  escalated?: boolean;
  citations?: Citation[];
}

export default function ChatScreen() {
  const requests = useRequestScope();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
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

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPatient || !input.trim() || sending) return;
    const isCurrent = requests.start('chat');

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      text: input.trim(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setSending(true);
    setError(null);
    const sentText = input.trim();
    setInput('');

    try {
      const result: ChatMessageResponse = await sendChat(selectedPatient.id, sentText);
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

  return (
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Chat</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ask questions about a patient’s diet plan. Citations link back to guidelines.
          </p>
        </div>

        <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <label htmlFor="chat-patient" className="mb-1 block text-sm font-medium text-slate-700">
            Patient
          </label>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : (
            <select
              id="chat-patient"
              value={selectedPatient?.id || ''}
              onChange={(e) => {
                requests.reset();
                const p = patients.find((pt) => pt.id === e.target.value) || null;
                setSelectedPatient(p);
                setMessages([]);
                setInput('');
                setError(null);
                setSending(false);
              }}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
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

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-medium underline">
              Dismiss
            </button>
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex h-96 flex-col">
            <div className="flex-1 overflow-y-auto p-4">
              {messages.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center text-center text-slate-500">
                  <p className="text-sm">Select a patient and type a message to begin.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-2xl rounded-2xl px-4 py-3 text-sm ${
                          msg.role === 'user'
                            ? 'bg-sky-600 text-white rounded-br-none'
                            : 'bg-slate-100 text-slate-900 rounded-bl-none'
                        }`}
                      >
                        <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                        {msg.role === 'assistant' && msg.escalated && (
                          <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-amber-800">
                            <svg className="mt-0.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 3.5V2m0 0a2.5 2.5 0 012.5 2.5v.5M21 9.5h-2.5m-4.5 0H9m-4.5 0H2m3 0v7.2a2 2 0 00.8 1.6l1.7 1.3a2 2 0 002.4 0l1.7-1.3a2 2 0 01.8-.2h4.6a2 2 0 01.8.2l1.7 1.3a2 2 0 002.4 0l1.7-1.3a2 2 0 00.8-1.6V9.5" />
                            </svg>
                            <span className="font-medium">A clinician will review this question.</span>
                          </div>
                        )}
                        {msg.role === 'assistant' && msg.citations && msg.citations.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {msg.citations.map((c, idx) => (
                              <a
                                key={idx}
                                href={c.url ?? undefined}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-white"
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

            <form onSubmit={handleSend} className="border-t border-slate-200 p-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={selectedPatient ? 'Type your question…' : 'Select a patient first'}
                  disabled={!selectedPatient || sending}
                  className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:ring-1 focus:ring-sky-500 disabled:bg-slate-100"
                />
                <button
                  type="submit"
                  disabled={!selectedPatient || sending || !input.trim()}
                  className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-700 disabled:bg-sky-300 transition-colors"
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
