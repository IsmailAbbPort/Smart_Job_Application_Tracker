import { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Modal } from "../../components/Modal";
import { SegmentedToggle } from "../../components/SegmentedToggle";
import { api } from "../../api";
import type { User } from "../../types";

type Mode = "signup" | "login";

// Password policy: min 6 chars, at least one number and one special char.
const rules = [
  { label: "At least 6 characters", test: (p: string) => p.length >= 6 },
  { label: "At least one number", test: (p: string) => /\d/.test(p) },
  { label: "At least one special character", test: (p: string) => /[^A-Za-z0-9]/.test(p) },
];
const passwordValid = (p: string) => rules.every((r) => r.test(p));
const emailValid = (e: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim());

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
  const [errs, setErrs] = useState<{
    name?: string;
    email?: string;
    password?: string;
    form?: string;
  }>({});
  const [busy, setBusy] = useState(false);

  const switchMode = (m: Mode) => {
    setMode(m);
    setErrs({});
  };

  const validate = (): boolean => {
    const next: typeof errs = {};
    if (mode === "signup" && !name.trim()) next.name = "Please enter your name";
    if (!emailValid(email)) next.email = "Enter a valid email address";
    if (mode === "signup") {
      if (!passwordValid(password)) next.password = "Password doesn't meet the requirements below";
    } else if (!password) {
      next.password = "Enter your password";
    }
    setErrs(next);
    return Object.keys(next).length === 0;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      const user =
        mode === "signup"
          ? await api.register({ name: name.trim(), email: email.trim(), password })
          : await api.login({ email: email.trim(), password });
      onAuthed(user);
      onOpenChange(false);
    } catch (err) {
      // Strip any trailing period so inline errors read cleanly (point 7).
      const msg = (err as Error).message.replace(/\.$/, "");
      // Route known server errors under the relevant field.
      if (/email already exists/i.test(msg)) setErrs({ email: msg });
      else if (/wrong email or password/i.test(msg)) setErrs({ password: msg });
      else setErrs({ form: msg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      anchorTop
      maxWidth={420}
      title="Save your job search"
    >
      <div className="modal-b">
        <p className="modal-text">
          An account isn&rsquo;t necessary to use this tool. But if you&rsquo;d like your shortlist,
          applications, and preferences saved for another session, you can create one.
        </p>

        <SegmentedToggle
          value={mode}
          onChange={(v) => switchMode(v as Mode)}
          options={[
            { value: "signup", label: "Sign up" },
            { value: "login", label: "Log in" },
          ]}
        />

        {/* noValidate suppresses Chrome's native bubbles; we show inline errors (point 18) */}
        <form onSubmit={submit} noValidate>
          {mode === "signup" && (
            <div className="field">
              <input
                className="input"
                placeholder="Your Name"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={!!errs.name}
              />
              {errs.name && <div className="field-error">{errs.name}</div>}
            </div>
          )}
          <div className="field">
            <input
              className="input"
              type="email"
              placeholder="you@example.com"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={!!errs.email}
            />
            {errs.email && <div className="field-error">{errs.email}</div>}
          </div>
          <div className="field">
            <input
              className="input"
              type="password"
              placeholder="Password"
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!errs.password}
            />
            {errs.password && <div className="field-error">{errs.password}</div>}
          </div>
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
          <button
            type="submit"
            className="btn primary"
            style={{ height: 34, justifyContent: "center" }}
            disabled={busy}
          >
            {busy ? (
              <span className="btn-spin">
                <Loader2 size={16} className="spin" />{" "}
                {mode === "login" ? "Logging in..." : "Signing up..."}
              </span>
            ) : mode === "login" ? (
              "Log in"
            ) : (
              "Sign up"
            )}
          </button>
        </form>

        {errs.form && <div className="modal-msg err">{errs.form}</div>}
        <button className="modal-skip" onClick={() => onOpenChange(false)}>
          Continue without an account
        </button>
      </div>
    </Modal>
  );
}

export { passwordValid };
