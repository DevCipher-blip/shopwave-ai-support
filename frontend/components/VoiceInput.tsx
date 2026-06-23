"use client";

import { useCallback, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { transcribeAudio } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

type VoiceState = "idle" | "recording" | "processing";

export function VoiceInput({ onTranscript, disabled }: Props) {
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked.");
      return;
    }
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      setState("processing");
      try {
        const text = await transcribeAudio(new Blob(chunksRef.current, { type: "audio/webm" }));
        if (text.trim()) onTranscript(text.trim());
        else setError("No speech detected.");
      } catch {
        setError("Transcription failed. Try again or type your message.");
      } finally {
        setState("idle");
      }
    };
    recorder.start();
    recorderRef.current = recorder;
    setState("recording");
  }, [onTranscript]);

  const handleClick = () => {
    if (disabled) return;
    if (state === "idle") startRecording();
    else if (state === "recording") recorderRef.current?.stop();
  };

  const label = state === "recording" ? "Stop recording" : state === "processing" ? "Transcribing" : "Speak your message";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || state === "processing"}
        aria-label={label}
        aria-pressed={state === "recording"}
        title={label}
        className={cn(
          "relative rounded-lg p-2 transition-colors",
          state === "recording" ? "bg-deny-soft text-deny" : "text-muted hover:bg-paper hover:text-ink",
          (disabled || state === "processing") && "cursor-not-allowed opacity-50"
        )}
      >
        {state === "processing" ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : state === "recording" ? (
          <Square className="h-4 w-4 fill-current" aria-hidden />
        ) : (
          <Mic className="h-4 w-4" aria-hidden />
        )}
      </button>
      {error && (
        <p role="alert" className="absolute bottom-full right-0 mb-2 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-card">
          {error}
        </p>
      )}
    </div>
  );
}
