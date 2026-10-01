// Spoken commands: hold the button (or V) and talk. The audio goes to the server, which has
// ElevenLabs turn it into words and Jev turn the words into one command.

export interface Heard {
  text?: string;
  command?: string;
  label?: string;
  probability?: number;
  error?: string;
}

export class Voice {
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;

  constructor(
    private onState: (state: "listening" | "thinking" | "idle") => void,
    private onHeard: (heard: Heard) => void,
  ) {}

  get supported(): boolean {
    return Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";
  }

  async start(): Promise<void> {
    if (this.recorder) return;
    try {
      this.stream ??= await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.onHeard({ error: "The microphone is blocked. Allow it for this page to use voice." });
      return;
    }
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (event) => this.chunks.push(event.data);
    this.recorder.onstop = () => void this.send();
    this.recorder.start();
    this.onState("listening");
  }

  stop(): void {
    if (this.recorder?.state === "recording") this.recorder.stop();
  }

  private async send(): Promise<void> {
    const type = this.recorder?.mimeType || "audio/webm";
    this.recorder = null;
    const audio = new Blob(this.chunks, { type });
    this.onState("thinking");
    try {
      const response = await fetch("/api/voice", { method: "POST", headers: { "Content-Type": type }, body: audio });
      this.onHeard((await response.json()) as Heard);
    } catch {
      this.onHeard({ error: "Voice is unavailable: the server could not be reached." });
    }
    this.onState("idle");
  }
}
