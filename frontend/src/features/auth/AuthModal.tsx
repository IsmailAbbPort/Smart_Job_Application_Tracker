import { useState } from "react";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { Modal } from "../../components/Modal";
import { api } from "../../api";
import type { User } from "../../types";

type Mode = "signup" | "login";

// Password policy (point 24): min 6 chars, at least one number and one special.
const rules = [
  { label: "At least 6 characters", test: (p: string) => p.length >= 6 },
  { label: "At least one number", test: (p: string) => /\d/.test(p) },
  { label: "At least one special character", test: (p: string) => /[^A-Za-z0-9]/.test(p) },
];
const passwordValid = (p: string) => rules.every((r) => r.test(p));

export function AuthModal({
  open,
  onOpenChange,
  onAuthed,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onAuthed: (user: User) => void;
}) {
  const [mode, setMode] = useState<Mode>("signup");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg("");
    if (mode === "signup" && !passwordValid(password)) {
      setMsg("Please meet all the password requirements.");
      return;
    }
    setBusy(true);
    try {
      const user =
        mode === "signup"
          ? await api.register({ name: name.trim(), email: email.trim(), password })
          : await api.login({ email: email.trim(), password });
      onAuthed(user);
      onOpenChange(false);
    } catch (err) {
      setMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={<h2>Hi! Let&rsquo;s find you a better job!</h2>}>
      <p className="modal-text">
        An account isn&rsquo;t necessary to use this tool. But if you&rsquo;d like your shortlist,
        applications, and preferences saved for another session, you can create one.
      </p>

      {/* Sliding-pill toggle (point 24), animated with framer-motion */}
      <div className="seg" role="tablist">
        <motion.div
          className="seg-slider"
          layout
          transition={{ type: "spring", stiffness: 500, damping: 38 }}
          style={{ left: mode === "signup" ? 3 : "50%" }}
        />
        <button
          type="button"
          className={"seg-btn" + (mode === "signup" ? " active" : "")}
          onClick={() => setMode("signup")}
        >
          Sign up
        </button>
        <button
          type="button"
          className={"seg-btn" + (mode === "login" ? " active" : "")}
          onClick={() => setMode("login")}
        >
          Log in
        </button>
      </div>

      <form onSubmit={submit}>
        {mode === "signup" && (
          <input
            className="input"
            placeholder="Your name"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        )}
        <input
          className="input"
          type="email"
          placeholder="you@example.com"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="input"
          type="password"
          placeholder="Password"
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {mode === "signup" && (
          <ul className="pw-rules">
            {rules.map((r) => {
              const met = r.test(password);
              return (
                <li key={r.label} className={met ? "met" : ""}>
                  <Check size={13} strokeWidth={met ? 3 : 2} /> {r.label}
                </li>
              );
            })}
          </ul>
        )}
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "..." : mode === "login" ? "Log in" : "Sign up"}
        </button>
      </form>

      {msg && <div className="modal-msg err">{msg}</div>}
      <button className="modal-skip" onClick={() => onOpenChange(false)}>
        Continue without an account &rarr;
      </button>
    </Modal>
  );
}

export { passwordValid };
