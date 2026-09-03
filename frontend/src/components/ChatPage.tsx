import { type FormEvent, useEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import { runCode } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import Sidebar from "./Sidebar";
import BillingModal from "./BillingModal";
import AgentsPanel from "./AgentsPanel";
import KBManagerModal from "./KBManagerModal";
import SearchModal from "./SearchModal";
import ProjectsModal from "./ProjectsModal";
import SettingsModal from "./SettingsModal";
import AdminPanel from "./AdminPanel";
import Markdown from "../lib/Markdown";
import { PROVIDERS, DEFAULT_PROVIDER, DEFAULT_MODEL, modelName } from "../lib/models";
import {
  BellIcon,
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  FolderIcon,
  GlobeIcon,
  MicIcon,
  SendIcon,
  SparklesIcon,
  SpeakerIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "../lib/icons";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  streaming?: boolean;
  is_edited?: boolean;
  citations?: api.Citation[];
  attachment?: {
    id: string;
    name: string;
    mime_type?: string;
    status?: string;
  };
}

const STARTER_PROMPTS = [
  "Brainstorm a launch plan for my new product",
  "Explain how vector databases work in simple terms",
  "Draft a professional email asking for a deadline extension",
];

const REACTION_KEY = "nova_reactions";

function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      resolve();
    } catch (e) {
      reject(e);
    } finally {
      document.body.removeChild(ta);
    }
  });
}

export default function ChatPage() {
  const { user, organization, signOut } = useAuth();
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const conversationsRef = useRef(conversations);
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [knowledgeBases, setKnowledgeBases] = useState<api.KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState<string>("");
  const [kbMenuOpen, setKbMenuOpen] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [uploading, setUploading] = useState(false); // eslint-disable-line
  const [editId, setEditId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [toast, setToast] = useState("");
  const [showBilling, setShowBilling] = useState(false);
  const [showAgents, setShowAgents] = useState(false);
  const [showKbManager, setShowKbManager] = useState(false);
  const [agents, setAgents] = useState<api.Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [agentsMenuOpen, setAgentsMenuOpen] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showProjects, setShowProjects] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<Blob[]>([]);
  const [showDownArrow, setShowDownArrow] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [followUps, setFollowUps] = useState<Record<string, string[]>>({});
  const [provider, setProvider] = useState<string>(DEFAULT_PROVIDER);
  const [model, setModel] = useState<string>(DEFAULT_MODEL);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [summary, setSummary] = useState<string>("");
  const [summarizing, setSummarizing] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speakCancelledRef = useRef(false);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const imageFileRef = useRef<File | null>(null);
  const [visionBusy, setVisionBusy] = useState(false); // eslint-disable-line
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [reactions, setReactions] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem(REACTION_KEY) ?? "{}") as Record<
        string,
        string
      >;
    } catch {
      return {};
    }
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    localStorage.getItem("nova_theme") === "light" ? "light" : "dark",
  );
  const [notifications, setNotifications] = useState<api.Notification[]>([]); // eslint-disable-line
  const [unread, setUnread] = useState(0); // eslint-disable-line
  const [notifOpen, setNotifOpen] = useState(false);

  const ACTIVE_KEY = "nova_active_conversation";
  const CHAT_STATE_KEY = "nova_chat_state";
  const DRAFT_PREFIX = "nova_draft:";

  useEffect(() => {
    document.documentElement.classList.toggle(
      "theme-light",
      theme === "light",
    );
    localStorage.setItem("nova_theme", theme);
  }, [theme]);

  useEffect(() => {
    api.listConversations().then((res) => {
      setConversations(res.conversations);
      const saved = localStorage.getItem(ACTIVE_KEY);
      if (saved && res.conversations.some((c) => c.id === saved)) {
        setActiveId(saved);
      }
    });
    api.listKnowledgeBases().then((res) => {
      setKnowledgeBases(res.knowledge_bases);
    });
    api.listAgents().then((res) => {
      setAgents(res);
    });
    api.unreadCount().then((n) => setUnread(n)).catch(() => undefined);
    const savedState = localStorage.getItem(CHAT_STATE_KEY);
    if (savedState) {
      try {
        const s = JSON.parse(savedState) as {
          selectedKb?: string;
          webSearch?: boolean;
        };
        if (s.selectedKb) setSelectedKb(s.selectedKb);
        if (typeof s.webSearch === "boolean") setWebSearch(s.webSearch);
      } catch {
        /* ignore malformed state */
      }
    }
  }, []);

  useEffect(() => {
    if (activeId) {
      localStorage.setItem(ACTIVE_KEY, activeId);
    } else {
      localStorage.removeItem(ACTIVE_KEY);
    }
  }, [activeId]);

  useEffect(() => {
    localStorage.setItem(
      CHAT_STATE_KEY,
      JSON.stringify({ selectedKb, webSearch }),
    );
  }, [selectedKb, webSearch]);

  // Code execution handler
  useEffect(() => {
    const handler = async (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!detail?.lang || !detail?.code) return;
      showToast("Running " + detail.lang + "...");
      try {
        const result = await runCode(detail.lang, detail.code);
        if (result.error) {
          showToast("Error: " + result.error);
        } else {
          showToast("Output: " + (result.output || "(no output)") + " (" + result.execution_time.toFixed(2) + "s)");
        }
      } catch (err) {
        showToast("Error: " + (err instanceof Error ? err.message : "Execution failed"));
      }
    };
    window.addEventListener("run-code", handler);
    return () => window.removeEventListener("run-code", handler);
  }, []);

  useEffect(() => {
    if (!activeId) return;
    const saved = localStorage.getItem(DRAFT_PREFIX + activeId);
    if (saved != null) setInput(saved);
  }, [activeId]);

  useEffect(() => {
    if (!activeId) return;
    const key = DRAFT_PREFIX + activeId;
    if (input) {
      localStorage.setItem(key, input);
    } else {
      localStorage.removeItem(key);
    }
  }, [input, activeId]);

  const handleSignOut = () => {
    localStorage.removeItem(ACTIVE_KEY);
    localStorage.removeItem(CHAT_STATE_KEY);
    Object.keys(localStorage)
      .filter((k) => k.startsWith(DRAFT_PREFIX))
      .forEach((k) => localStorage.removeItem(k));
    signOut();
  };

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      setFollowUps({});
      setSummary("");
      return;
    }
    setMessages([]);
    setFollowUps({});
    setSummary(
      conversationsRef.current.find((c) => c.id === activeId)?.summary ?? "",
    );
    api
      .listMessages(activeId)
      .then((res) => {
        setMessages(
          res.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content ?? "",
            is_edited: m.is_edited,
            citations: Array.isArray(m.citations)
              ? (m.citations as api.Citation[])
              : undefined,
          })),
        );
      })
      .catch(() => setMessages([]));
  }, [activeId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      setShowDownArrow(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && !showDownArrow) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages, showDownArrow]);

  const showToast = (text: string) => {
    setToast(text);
    setTimeout(() => setToast(""), 1800);
  };

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      setShowDownArrow(false);
    }
  };

  const handleNew = async () => {
    const conv = await api.createConversation("New conversation");
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
  };

  const runStream = async (
    content: string,
    conversationId: string,
    kbs?: string[],
    ws?: boolean,
    agentId?: string,
  ) => {
    const userMsg: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
    };
    const assistantMsg: ChatMessage = {
      id: `local-${Date.now() + 1}`,
      role: "assistant",
      content: "",
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await api.streamChat(
        conversationId,
        content,
        (event) => {
          if (event.type === "content") {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  content: last.content + event.content,
                };
              }
              return next;
            });
          } else if (event.type === "citations") {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  citations: (event.citations as api.Citation[]) ?? [],
                };
              }
              return next;
            });
          } else if (event.type === "error") {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  streaming: false,
                  content: last.content || "⚠ " + event.message,
                };
              }
              return next;
            });
          } else if (event.type === "done") {
            const doneId = event.message_id;
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  streaming: false,
                  id: doneId,
                };
              }
              return next;
            });
            api
              .listConversations()
              .then((res) => setConversations(res.conversations));
            api
              .listMessages(conversationId)
              .then((res) => {
                setMessages(
                  res.messages.map((m) => ({
                    id: m.id,
                    role: m.role,
                    content: m.content ?? "",
                    is_edited: m.is_edited,
                    citations: Array.isArray(m.citations)
                      ? (m.citations as api.Citation[])
                      : undefined,
                  })),
                );
              })
              .catch(() => undefined);
            if (doneId) {
              api
                .suggestFollowups(conversationId)
                .then((s) => {
                  if (s.length > 0) {
                    setFollowUps((prev) => ({ ...prev, [doneId]: s }));
                  }
                })
                .catch(() => undefined);
            }
          }
        },
        controller.signal,
        kbs,
        ws,
        agentId,
        model,
        provider,
      );
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.streaming) {
          next[next.length - 1] = {
            ...last,
            streaming: false,
            content:
              last.content ||
              "⚠ " + (err instanceof Error ? err.message : "Stream failed"),
          };
        }
        return next;
      });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const sendText = async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    let convId = activeId;
    if (!convId) {
      const conv = await api.createConversation("New conversation");
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.id);
      convId = conv.id;
    }
    setInput("");
    setImagePreview(null);
    imageFileRef.current = null;
    await runStream(
      content,
      convId,
      knowledgeBaseIds,
      webSearch,
      selectedAgent || undefined,
    );
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (imagePreview && imageFileRef.current) {
      await sendVision();
      return;
    }
    await sendText(input);
  };

  const sendVision = async () => {
    const file = imageFileRef.current;
    if (!file || !activeId || busy) return;
    const question = input.trim() || "What is in this image?";
    setVisionBusy(true);
    try {
      const answer = await api.analyzeImage(file, question);
      const userText = `[Image: ${file.name}]\n${question}`;
      setMessages((prev) => [
        ...prev,
        { id: `local-v${Date.now()}`, role: "user", content: userText },
        {
          id: `local-v${Date.now() + 1}`,
          role: "assistant",
          content: answer,
        },
      ]);
      await api.createMessage(activeId, { role: "user", content: userText });
      await api.createMessage(activeId, { role: "assistant", content: answer });
      api
        .listConversations()
        .then((res) => setConversations(res.conversations));
      api
        .listMessages(activeId)
        .then((res) => {
          setMessages(
            res.messages.map((m) => ({
              id: m.id,
              role: m.role,
              content: m.content ?? "",
              is_edited: m.is_edited,
              citations: Array.isArray(m.citations)
                ? (m.citations as api.Citation[])
                : undefined,
            })),
          );
        })
        .catch(() => undefined);
      setInput("");
      setImagePreview(null);
      imageFileRef.current = null;
      showToast("Image analyzed");
    } catch (err) {
      showToast(
        "⚠ " + (err instanceof Error ? err.message : "Vision failed"),
      );
    } finally {
      setVisionBusy(false);
    }
  };

  const handleStop = () => abortRef.current?.abort();

  const startEdit = (m: ChatMessage) => {
    setEditId(m.id);
    setEditText(m.content);
  };

  const cancelEdit = () => {
    setEditId(null);
    setEditText("");
  };

  const saveEdit = async () => {
    const text = editText.trim();
    const target = messages.find((x) => x.id === editId);
    if (!activeId || !target || !text) return;
    setEditId(null);
    setEditText("");
    if (target.id.startsWith("local-")) return;

    const idx = messages.findIndex((x) => x.id === target.id);
    const toDelete = messages
      .slice(idx)
      .filter((x) => !x.id.startsWith("local-"));
    await Promise.all(
      toDelete.map((x) =>
        api.deleteMessage(activeId, x.id).catch(() => undefined),
      ),
    );
    setMessages((prev) => prev.slice(0, idx));
    await runStream(
      text,
      activeId,
      knowledgeBaseIds,
      webSearch,
      selectedAgent || undefined,
    );
  };

  const copyMessage = async (m: ChatMessage) => {
    try {
      await copyToClipboard(m.content);
      showToast("Copied to clipboard");
    } catch {
      showToast("Copy failed");
    }
  };

  const removeMessage = async (m: ChatMessage) => {
    if (!activeId || m.id.startsWith("local-") || busy) return;
    const idx = messages.findIndex((x) => x.id === m.id);
    const toDelete = messages
      .slice(idx)
      .filter((x) => !x.id.startsWith("local-"));
    await Promise.all(
      toDelete.map((x) =>
        api.deleteMessage(activeId, x.id).catch(() => undefined),
      ),
    );
    setMessages((prev) => prev.slice(0, idx));
  };

  const splitForSpeech = (text: string): string[] => {
    const parts: string[] = [];
    const segments = text.split(/(?<=[.!?\u0964\u2026])\s+|\n+/);
    let cur = "";
    for (const seg of segments) {
      const s = seg.trim();
      if (!s) continue;
      if (cur && (cur + " " + s).length > 320) {
        parts.push(cur);
        cur = s;
      } else {
        cur = cur ? `${cur} ${s}` : s;
      }
    }
    if (cur) parts.push(cur);
    return parts.length ? parts : [text];
  };

  const stopSpeak = () => {
    speakCancelledRef.current = true;
    audioRef.current?.pause();
    audioRef.current = null;
    setSpeakingId(null);
  };

  const handleSpeak = async (m: ChatMessage) => {
    if (!m.content) return;
    if (speakingId === m.id) {
      stopSpeak();
      return;
    }
    stopSpeak();
    speakCancelledRef.current = false;
    setSpeakingId(m.id);
    const chunks = splitForSpeech(m.content);
    try {
      for (const chunk of chunks) {
        if (speakCancelledRef.current) break;
        const blob = await api.synthesizeVoice(chunk);
        if (speakCancelledRef.current) break;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise<void>((resolve) => {
          audio.onended = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            setSpeakingId(null);
            resolve();
          };
          audio.play();
        });
        if (speakCancelledRef.current) break;
      }
    } catch (err) {
      showToast(
        "⚠ " + (err instanceof Error ? err.message : "Speech failed"),
      );
    } finally {
      if (!speakCancelledRef.current) setSpeakingId(null);
      speakCancelledRef.current = false;
    }
  };

  const setReaction = (id: string, r: string) => {
    const next = { ...reactions };
    if (next[id] === r) delete next[id];
    else next[id] = r;
    setReactions(next);
    localStorage.setItem(REACTION_KEY, JSON.stringify(next));
  };

  const handlePin = async (id: string, pinned: boolean) => {
    try {
      const updated = await api.updateConversation(id, { is_pinned: pinned });
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, is_pinned: updated.is_pinned } : c)),
      );
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Pin failed"));
    }
  };

  const handleFolder = async (id: string, folder: string | null) => {
    try {
      const updated = await api.updateConversation(id, { folder });
      setConversations((prev) =>
        prev.map((c) =>
          c.id === id ? { ...c, settings: updated.settings } : c,
        ),
      );
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Folder failed"));
    }
  };

  const handleSummarize = async () => {
    if (!activeId || messages.length === 0 || summarizing) return;
    setSummarizing(true);
    try {
      const s = await api.summarizeConversation(activeId);
      setSummary(s);
      setConversations((prev) =>
        prev.map((c) => (c.id === activeId ? { ...c, summary: s } : c)),
      );
      showToast("Summary generated");
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Summarize failed"));
    } finally {
      setSummarizing(false);
    }
  };

  const handleShare = async () => {
    if (!activeId) return;
    try {
      const res = await api.shareConversation(activeId);
      await copyToClipboard(res.url);
      showToast("Share link copied");
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Share failed"));
    }
  };

  const toggleNotifications = async () => { // eslint-disable-line
    const next = !notifOpen;
    setNotifOpen(next);
    if (next) {
      try {
        const items = await api.listNotifications();
        setNotifications(items);
        await api.markAllNotificationsRead();
        setUnread(0);
      } catch {
        /* ignore */
      }
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      let kbId = selectedKb;
      if (!kbId) {
        const existing = knowledgeBases[0];
        if (existing) {
          kbId = existing.id;
          setSelectedKb(kbId);
        } else {
          const kb = await api.createKnowledgeBase(
            "My Documents",
            "Uploaded documents",
          );
          kbId = kb.id;
          setSelectedKb(kbId);
          api
            .listKnowledgeBases()
            .then((res) => setKnowledgeBases(res.knowledge_bases));
        }
      }
      const record = await api.uploadFile(kbId, file);
      let status = record.status ?? "";
      for (let i = 0; i < 20 && status !== "ready"; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const fresh = await api.getFile(record.id);
          status = fresh.status ?? status;
        } catch {
          break;
        }
      }
      const att = {
        id: record.id,
        name: record.original_filename,
        mime_type: record.mime_type,
        status,
      };
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}`,
          role: "assistant",
          content: `PDF "${record.original_filename}" uploaded and indexed. What details would you like me to extract from it?`,
          attachment: att,
        },
      ]);
      showToast("PDF uploaded");
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Upload failed"));
    } finally {
      setUploading(false);
    }
  };

  const handleAttachClick = () => {
    fileInputRef.current?.click();
  };

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast("Please pick an image file");
      return;
    }
    imageFileRef.current = file;
    setImagePreview(URL.createObjectURL(file));
  };

  const openAttachment = async (
    att: NonNullable<ChatMessage["attachment"]>,
  ) => {
    try {
      await api.openFile(att.id);
    } catch (err) {
      showToast(
        "⚠ " + (err instanceof Error ? err.message : "Failed to open file"),
      );
    }
  };

  const handleRename = async (id: string, title: string) => {
    try {
      const updated = await api.renameConversation(id, title);
      setConversations((prev) =>
        prev.map((c) =>
          c.id === id ? { ...c, title: updated.title ?? title } : c,
        ),
      );
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Rename failed"));
    }
  };

  const handleDeleteConv = async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
      }
      showToast("Conversation deleted");
    } catch (err) {
      showToast("⚠ " + (err instanceof Error ? err.message : "Delete failed"));
    }
  };

  const toggleRecording = async () => {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType: mime });
      mediaChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) mediaChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(mediaChunksRef.current, { type: "audio/webm" });
        if (blob.size === 0) return;
        setTranscribing(true);
        try {
          const text = await api.transcribeVoice(
            new File([blob], "recording.webm", { type: "audio/webm" }),
          );
          if (text) {
            setInput((prev) => (prev ? prev + " " + text : text));
            showToast("Voice transcribed");
          } else {
            showToast("No speech detected");
          }
        } catch (err) {
          showToast(
            "⚠ " +
              (err instanceof Error ? err.message : "Transcription failed"),
          );
        } finally {
          setTranscribing(false);
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      showToast("⚠ Microphone unavailable");
    }
  };

  const exportConversation = () => {
    if (messages.length === 0) return;
    const title = activeId
      ? (conversations.find((c) => c.id === activeId)?.title ?? "conversation")
      : "conversation";
    const lines: string[] = [`# ${title}`, ""];
    for (const m of messages) {
      const role = m.role === "user" ? "**You**" : "**Nova**";
      const body = m.content.replace(/\n+$/g, "");
      lines.push(`${role}:`, "", body, "");
    }
    const blob = new Blob([lines.join("\n")], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.replace(/[^\w\d-]+/g, "_").slice(0, 60)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast("Conversation exported");
  };

  const knowledgeBaseIds = selectedKb ? [selectedKb] : undefined;
  const selectedKbName =
    knowledgeBases.find((k) => k.id === selectedKb)?.name ?? "";
  const selectedAgentName =
    agents.find((a) => a.id === selectedAgent)?.name ?? "";

  return (
    <div className="app-shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onRename={handleRename}
        onDelete={handleDeleteConv}
        onPin={handlePin}
        onFolder={handleFolder}
        user={user}
        theme={theme}
        canExport={messages.length > 0}
        canSummarize={!!activeId && messages.length > 0 && !summarizing}
        summarizing={summarizing}
        onSearch={() => setShowSearch(true)}
        onProjects={() => setShowProjects(true)}
        onExport={exportConversation}
        onSummarize={handleSummarize}
        onShare={handleShare}
        onBilling={() => setShowBilling(true)}
        onAdmin={() => setShowAdmin(true)}
        onSettings={() => setShowSettings(true)}
        onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        onSignOut={handleSignOut}
      />

      <main className="chatgpt-main">
        <header className="chatgpt-header">
          <div className="chatgpt-tabs">
            <button className="chatgpt-tab active">Chat</button>
            <button className="chatgpt-tab">✨ Work</button>
          </div>
        </header>

        <div className="message-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chatgpt-greeting">
              <h1>What's on the agenda today?</h1>
              <div className="chatgpt-starters">
                {STARTER_PROMPTS.map((p) => (
                  <button
                    key={p}
                    className="chatgpt-starter"
                    onClick={() => sendText(p)}
                    disabled={busy}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {summary && (
            <div className="summary-banner">
              <div className="summary-head">
                <SparklesIcon />
                <span>Summary</span>
                <button className="summary-close" onClick={() => setSummary("")}>
                  ×
                </button>
              </div>
              <div className="summary-body">
                <Markdown text={summary} />
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div
              key={m.id}
              className={`message-row ${m.role}${m.id === editId ? " editing" : ""}`}
            >
              <div className="message-avatar">
                {m.role === "user" ? "You" : "AI"}
              </div>
              <div className="message-main">
                <div className="message-bubble">
                  <div className="message-head">
                    <span className="message-role-label">
                      {m.role === "user" ? "You" : "Nova"}
                      {m.is_edited && (
                        <span className="edited-tag"> (edited)</span>
                      )}
                    </span>
                  </div>
                  {m.id === editId ? (
                    <div className="edit-box">
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && (e.ctrlKey || e.metaKey))
                            saveEdit();
                          if (e.key === "Escape") cancelEdit();
                        }}
                      />
                      <div className="edit-actions">
                        <button className="edit-save" onClick={saveEdit}>
                          Save &amp; Resend
                        </button>
                        <button className="edit-cancel" onClick={cancelEdit}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="message-content">
                      {m.role === "assistant" ? (
                        <Markdown text={m.content} />
                      ) : (
                        m.content
                      )}
                      {m.streaming &&
                        (m.content ? (
                          <span className="cursor-blink" />
                        ) : (
                          <span className="typing-dots">
                            <i />
                            <i />
                            <i />
                          </span>
                        ))}
                    </div>
                  )}
                  {m.attachment && (
                    <button
                      type="button"
                      className="file-chip"
                      onClick={() => openAttachment(m.attachment!)}
                      title="Open PDF"
                    >
                      <span className="file-chip-icon">PDF</span>
                      <span className="file-chip-name">
                        {m.attachment.name}
                      </span>
                      <span className="file-chip-open">Open</span>
                    </button>
                  )}
                </div>
                {m.role === "assistant" &&
                  m.citations &&
                  m.citations.length > 0 &&
                  !m.streaming && (
                    <div className="sources">
                      <span className="sources-label">Sources</span>
                      <div className="sources-list">
                        {m.citations.map((c) => (
                          <a
                            key={c.index}
                            className={`source-chip${c.type === "video" ? " video" : ""}`}
                            href={c.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span className="source-idx">{c.index}</span>
                            <span className="source-title">
                              {c.type === "video"
                                ? `▶ ${c.title ?? c.url}`
                                : (c.title ?? c.url)}
                            </span>
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                {!m.streaming && (
                  <div className="message-footer">
                    <button
                      className="msg-action"
                      onClick={() => copyMessage(m)}
                    >
                      Copy
                    </button>
                    {m.role === "user" && (
                      <button
                        className="msg-action"
                        onClick={() => startEdit(m)}
                      >
                        Edit
                      </button>
                    )}
                    {m.role === "assistant" && (
                      <>
                        <button
                          className={`msg-action${speakingId === m.id ? " active" : ""}`}
                          onClick={() => handleSpeak(m)}
                          title={speakingId === m.id ? "Stop reading" : "Read aloud"}
                        >
                          <SpeakerIcon />
                          {speakingId === m.id ? "Stop" : "Listen"}
                        </button>
                        <button
                          className={`msg-action reaction${reactions[m.id] === "up" ? " active" : ""}`}
                          onClick={() => setReaction(m.id, "up")}
                          title="Good answer"
                        >
                          <ThumbsUpIcon />
                        </button>
                        <button
                          className={`msg-action reaction${reactions[m.id] === "down" ? " active" : ""}`}
                          onClick={() => setReaction(m.id, "down")}
                          title="Bad answer"
                        >
                          <ThumbsDownIcon />
                        </button>
                      </>
                    )}
                    <button
                      className="msg-action danger"
                      onClick={() => removeMessage(m)}
                    >
                      Delete
                    </button>
                  </div>
                )}
                {followUps[m.id] &&
                  followUps[m.id].length > 0 &&
                  !m.streaming &&
                  !busy && (
                    <div className="followups">
                      {followUps[m.id].map((q, i) => (
                        <button
                          key={i}
                          className="followup-chip"
                          onClick={() => sendText(q)}
                          disabled={busy}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
              </div>
            </div>
          ))}
        </div>

        {showDownArrow && (
          <button
            className="scroll-down"
            onClick={scrollToBottom}
            title="Scroll to latest"
          >
            <ChevronDownIcon />
          </button>
        )}

        <form className="chatgpt-composer" onSubmit={handleSubmit}>
          <div className="chatgpt-input-wrap">
            {imagePreview && (
              <div className="image-preview">
                <img src={imagePreview} alt="Attachment preview" />
                <button
                  type="button"
                  className="image-preview-remove"
                  onClick={() => {
                    setImagePreview(null);
                    imageFileRef.current = null;
                  }}
                >
                  ×
                </button>
              </div>
            )}
            <button
              type="button"
              className="chatgpt-attach-btn"
              onClick={handleAttachClick}
              title="Attach file"
            >
              <span style={{fontSize: '20px', lineHeight: 1}}>+</span>
            </button>
            <input
              className="chatgpt-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Nova anything…"
              disabled={!activeId || busy}
            />
            <div className="chatgpt-input-icons">
              <button
                type="button"
                className={`chatgpt-icon-btn${modelMenuOpen ? " active" : ""}`}
                title="Choose model"
                onClick={() => setModelMenuOpen((o) => !o)}
              >
                <SparklesIcon />
              </button>
              {modelMenuOpen && (
                <div className="chatgpt-model-menu">
                  {PROVIDERS.map((p) => (
                    <div key={p.id} className="model-menu-group">
                      <div className="model-menu-label">{p.label}</div>
                      {p.models.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          className={`kb-menu-item${provider === p.id && model === m.id ? " selected" : ""}`}
                          onClick={() => {
                            setProvider(p.id);
                            setModel(m.id);
                            setModelMenuOpen(false);
                          }}
                        >
                          {m.name}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              <button
                type="button"
                className={`chatgpt-icon-btn${webSearch ? " active" : ""}`}
                title="Live web search"
                onClick={() => setWebSearch((v) => !v)}
              >
                <GlobeIcon />
              </button>
              <button
                type="button"
                className={`chatgpt-icon-btn${recording ? " recording" : ""}`}
                title={recording ? "Stop recording" : "Speak your message"}
                disabled={transcribing}
                onClick={toggleRecording}
              >
                <MicIcon />
              </button>

              {busy ? (
                <button
                  type="button"
                  className="chatgpt-stop-btn"
                  onClick={handleStop}
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  className="chatgpt-send-btn"
                  disabled={!activeId || (!input.trim() && !imagePreview)}
                  title="Send"
                >
                  <SendIcon />
                </button>
              )}
            </div>
            {agentsMenuOpen && (
              <div className="kb-menu">
                {selectedAgent && (
                  <button
                    className="kb-menu-item"
                    onClick={() => {
                      setSelectedAgent("");
                      setAgentsMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-clear">
                      Chat with Nova (default)
                    </span>
                  </button>
                )}
                {agents.length === 0 && (
                  <div className="kb-menu-empty">No agents yet</div>
                )}
                {agents.map((a) => (
                  <button
                    key={a.id}
                    className={`kb-menu-item${selectedAgent === a.id ? " selected" : ""}`}
                    onClick={() => {
                      setSelectedAgent(a.id);
                      setAgentsMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-check">
                      {selectedAgent === a.id && <CheckIcon />}
                    </span>
                    <span className="kb-menu-name">{a.name}</span>
                    <span className="kb-menu-count">{a.model_provider}</span>
                  </button>
                ))}
                <button
                  className="kb-menu-item"
                  onClick={() => {
                    setAgentsMenuOpen(false);
                    setShowAgents(true);
                  }}
                >
                  <span className="kb-menu-clear">+ Manage agents</span>
                </button>
              </div>
            )}
            {kbMenuOpen && (
              <div className="kb-menu">
                {selectedKb && (
                  <button
                    className="kb-menu-item"
                    onClick={() => {
                      setSelectedKb("");
                      setKbMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-clear">Clear selection</span>
                  </button>
                )}
                {knowledgeBases.length === 0 && (
                  <div className="kb-menu-empty">No knowledge bases yet</div>
                )}
                {knowledgeBases.map((kb) => (
                  <button
                    key={kb.id}
                    className={`kb-menu-item${selectedKb === kb.id ? " selected" : ""}`}
                    onClick={() => {
                      setSelectedKb(kb.id);
                      setKbMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-check">
                      {selectedKb === kb.id && <CheckIcon />}
                    </span>
                    <span className="kb-menu-name">{kb.name}</span>
                    <span className="kb-menu-count">
                      {kb.total_chunks} chunks
                    </span>
                  </button>
                ))}
                <button
                  className="kb-menu-item"
                  onClick={() => {
                    setKbMenuOpen(false);
                    setShowKbManager(true);
                  }}
                >
                  <span className="kb-menu-clear">
                    + Manage knowledge bases
                  </span>
                </button>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={handleFileSelect}
            />
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={handleImageSelect}
            />
          </div>
        </form>
      </main>

      {showBilling && (
        <BillingModal
          organizationId={organization?.id}
          onClose={() => setShowBilling(false)}
        />
      )}
      {showAgents && (
        <AgentsPanel
          knowledgeBases={knowledgeBases}
          onClose={() => setShowAgents(false)}
        />
      )}
      {showKbManager && (
        <KBManagerModal
          knowledgeBases={knowledgeBases}
          selectedKb={selectedKb || knowledgeBases[0]?.id || ""}
          onClose={() => setShowKbManager(false)}
          onChanged={() => {
            api
              .listKnowledgeBases()
              .then((res) => setKnowledgeBases(res.knowledge_bases));
          }}
        />
      )}
      {showSearch && (
        <SearchModal
          onClose={() => setShowSearch(false)}
          onOpenConversation={(id) => setActiveId(id)}
        />
      )}
      {showProjects && (
        <ProjectsModal
          organizationId={organization?.id}
          onClose={() => setShowProjects(false)}
        />
      )}
      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          onToast={showToast}
        />
      )}
      {showAdmin && (
        <AdminPanel
          onClose={() => setShowAdmin(false)}
          onToast={showToast}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
