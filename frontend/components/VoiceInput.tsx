"use client";

import { useState, useRef, useCallback } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
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
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });
      chunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setState("processing");
        try {
          const blob = new Blob(chunksRef.current, { type: "audio/webm" });
          const text = await transcribeAudio(blob);
          if (text?.trim()) {
            onTranscript(text.trim());
          } else {
            setError("No speech detected");
          }
        } catch {
          setError("Transcription failed. Check your microphone.");
        } finally {
          setState("idle");
        }
      };
      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setState("recording");
    } catch {
      setError("Microphone access denied");
      setState("idle");
    }
  }, [onTranscript]);

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop();
  }, []);

  const handleClick = () => {
    if (disabled) return;
    if (state === "idle") startRecording();
    else if (state === "recording") stopRecording();
  };

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        disabled={disabled || state === "processing"}
        title={state === "recording" ? "Stop recording" : "Start voice input"}
        className={cn(
          "p-2 rounded-lg transition-all duration-200 relative",
          state === "recording"
            ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
            : state === "processing"
            ? "text-brand-400 cursor-wait"
            : "text-gray-400 hover:text-white hover:bg-surface-4",
          disabled && "opacity-40 cursor-not-allowed"
        )}
      >
        {state === "processing" ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : state === "recording" ? (
          <>
            <MicOff className="w-4 h-4" />
            {/* Pulse ring */}
            <span className="absolute inset-0 rounded-lg border-2 border-red-500 animate-ping opacity-40" />
          </>
        ) : (
          <Mic className="w-4 h-4" />
        )}
      </button>
      {error && (
        <div className="absolute bottom-full mb-1 right-0 bg-red-900/90 text-red-200 text-xs px-2 py-1 rounded whitespace-nowrap">
          {error}
        </div>
      )}
    </div>
  );
}
