import { useEffect, useState } from "react";
import {
  AppState,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import type { Session } from "@supabase/supabase-js";

import { bintuApiUrl, supabase } from "./supabase";

type AuthMode = "signIn" | "signUp";

type ScrapeResult = {
  url: string;
  text: string;
  truncated: boolean;
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function isScrapeResult(value: unknown): value is ScrapeResult {
  if (typeof value !== "object" || value === null) return false;
  return (
    "url" in value &&
    typeof value.url === "string" &&
    "text" in value &&
    typeof value.text === "string" &&
    "truncated" in value &&
    typeof value.truncated === "boolean"
  );
}

function getApiErrorMessage(value: unknown): string | undefined {
  if (typeof value !== "object" || value === null || !("detail" in value)) {
    return undefined;
  }
  const detail = value.detail;
  if (typeof detail !== "object" || detail === null || !("message" in detail)) {
    return undefined;
  }
  return typeof detail.message === "string" ? detail.message : undefined;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<ScrapeResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void supabase.auth.getSession().then(({ data, error }) => {
      if (!active) return;
      if (error) setAuthMessage(error.message);
      setSession(data.session);
      setAuthReady(true);
    }).catch((error: unknown) => {
      if (!active) return;
      setAuthMessage(getErrorMessage(error));
      setAuthReady(true);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!active) return;
      setSession(nextSession);
      setAuthReady(true);
    });
    const appStateSubscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        supabase.auth.startAutoRefresh();
      } else {
        supabase.auth.stopAutoRefresh();
      }
    });
    if (AppState.currentState === "active") {
      supabase.auth.startAutoRefresh();
    }

    return () => {
      active = false;
      subscription.unsubscribe();
      appStateSubscription.remove();
      supabase.auth.stopAutoRefresh();
    };
  }, []);

  async function submitAuth(): Promise<void> {
    setBusy(true);
    setAuthMessage("");
    try {
      if (authMode === "signUp") {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
        });
        if (error) throw error;
        if (!data.session) {
          setAuthMessage("Check your email to verify your account, then sign in.");
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
      }
    } catch (error) {
      setAuthMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function extractText(): Promise<void> {
    setErrorMessage("");
    setResult(null);
    let parsedUrl: URL;
    try {
      parsedUrl = new URL(url.trim());
    } catch {
      setErrorMessage("Enter a complete webpage address, such as https://example.com.");
      return;
    }
    if (!["http:", "https:"].includes(parsedUrl.protocol)) {
      setErrorMessage("Only public HTTP and HTTPS webpages are supported.");
      return;
    }
    if (!session) {
      setErrorMessage("Sign in again to continue.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${bintuApiUrl}/api/v1/mobile/scrape/text`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: parsedUrl.toString() }),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        const detail = getApiErrorMessage(body);
        throw new Error(
          typeof detail === "string"
            ? detail
            : `The request failed (HTTP ${response.status}).`,
        );
      }
      if (!isScrapeResult(body)) {
        throw new Error("The API returned an unexpected response.");
      }
      setResult(body);
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function signOut(): Promise<void> {
    setBusy(true);
    setAuthMessage("");
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
      setResult(null);
      setUrl("");
    } catch (error) {
      setAuthMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (!authReady) {
    return (
      <SafeAreaView style={styles.loadingScreen}>
        <StatusBar barStyle="light-content" />
        <ActivityIndicator color="#a78bfa" size="large" />
        <Text style={styles.muted}>Loading Bintu...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.screen}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.header}>
            <View style={styles.logo}>
              <Text style={styles.logoText}>B</Text>
            </View>
            <View>
              <Text style={styles.brand}>Bintu</Text>
              <Text style={styles.tagline}>Read the web, without the clutter.</Text>
            </View>
          </View>

          {!session ? (
            <View style={styles.card}>
              <Text style={styles.eyebrow}>YOUR READING SPACE</Text>
              <Text style={styles.title}>
                {authMode === "signIn" ? "Welcome back" : "Create your account"}
              </Text>
              <Text style={styles.muted}>
                Sign in to turn a public webpage into clean, readable text.
              </Text>
              <TextInput
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                onChangeText={setEmail}
                placeholder="Email address"
                placeholderTextColor="#8e8b9a"
                style={styles.input}
                value={email}
              />
              <TextInput
                autoCapitalize="none"
                onChangeText={setPassword}
                placeholder="Password"
                placeholderTextColor="#8e8b9a"
                secureTextEntry
                style={styles.input}
                value={password}
              />
              {authMessage ? <Text style={styles.notice}>{authMessage}</Text> : null}
              <Pressable
                accessibilityRole="button"
                disabled={busy}
                onPress={() => void submitAuth()}
                style={({ pressed }) => [
                  styles.primaryButton,
                  (pressed || busy) && styles.buttonPressed,
                ]}
              >
                {busy ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.primaryButtonText}>
                    {authMode === "signIn" ? "Sign in" : "Create account"}
                  </Text>
                )}
              </Pressable>
              <Pressable
                accessibilityRole="button"
                onPress={() => {
                  setAuthMessage("");
                  setAuthMode(authMode === "signIn" ? "signUp" : "signIn");
                }}
              >
                <Text style={styles.switchText}>
                  {authMode === "signIn"
                    ? "New to Bintu? Create an account"
                    : "Already have an account? Sign in"}
                </Text>
              </Pressable>
            </View>
          ) : (
            <>
              <View style={styles.card}>
                <View style={styles.signedInRow}>
                  <View style={styles.flex}>
                    <Text style={styles.eyebrow}>SIGNED IN</Text>
                    <Text style={styles.email}>{session.user.email}</Text>
                  </View>
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => void signOut()}
                  >
                    <Text style={styles.signOut}>Sign out</Text>
                  </Pressable>
                </View>
                <Text style={styles.title}>What would you like to read?</Text>
                <Text style={styles.muted}>
                  Paste a link to a public webpage. Bintu extracts its readable text.
                </Text>
                <TextInput
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="url"
                  onChangeText={setUrl}
                  onSubmitEditing={() => void extractText()}
                  placeholder="https://example.com/article"
                  placeholderTextColor="#8e8b9a"
                  returnKeyType="go"
                  style={styles.input}
                  value={url}
                />
                {errorMessage ? <Text style={styles.error}>{errorMessage}</Text> : null}
                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  onPress={() => void extractText()}
                  style={({ pressed }) => [
                    styles.primaryButton,
                    (pressed || busy) && styles.buttonPressed,
                  ]}
                >
                  {busy ? (
                    <ActivityIndicator color="#ffffff" />
                  ) : (
                    <Text style={styles.primaryButtonText}>Extract text</Text>
                  )}
                </Pressable>
              </View>

              {result ? (
                <View style={styles.resultCard}>
                  <Text style={styles.eyebrow}>EXTRACTED TEXT</Text>
                  <Text numberOfLines={2} style={styles.resultUrl}>
                    {result.url}
                  </Text>
                  {result.truncated ? (
                    <Text style={styles.notice}>
                      This page was shortened to fit the service text limit.
                    </Text>
                  ) : null}
                  <Text selectable style={styles.resultText}>
                    {result.text || "No readable text was found on this page."}
                  </Text>
                </View>
              ) : null}

              <Text style={styles.footnote}>
                Only process pages you are authorized to access.
              </Text>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { backgroundColor: "#111018", flex: 1 },
  loadingScreen: {
    alignItems: "center",
    backgroundColor: "#111018",
    flex: 1,
    gap: 14,
    justifyContent: "center",
  },
  flex: { flex: 1 },
  screen: { flexGrow: 1, padding: 22, paddingTop: 28 },
  header: { alignItems: "center", flexDirection: "row", gap: 13, marginBottom: 34 },
  logo: {
    alignItems: "center",
    backgroundColor: "#7c3aed",
    borderRadius: 15,
    height: 48,
    justifyContent: "center",
    width: 48,
  },
  logoText: { color: "#ffffff", fontSize: 25, fontWeight: "800" },
  brand: { color: "#faf9ff", fontSize: 21, fontWeight: "700" },
  tagline: { color: "#a7a3b4", fontSize: 12, marginTop: 2 },
  card: {
    backgroundColor: "#1b1924",
    borderColor: "#302c3a",
    borderRadius: 22,
    borderWidth: 1,
    padding: 21,
  },
  eyebrow: { color: "#b49aff", fontSize: 11, fontWeight: "700", letterSpacing: 1.4 },
  title: { color: "#faf9ff", fontSize: 24, fontWeight: "700", marginTop: 14 },
  muted: { color: "#b0acba", fontSize: 14, lineHeight: 21, marginTop: 8 },
  input: {
    backgroundColor: "#111018",
    borderColor: "#393444",
    borderRadius: 12,
    borderWidth: 1,
    color: "#faf9ff",
    fontSize: 15,
    marginTop: 15,
    minHeight: 52,
    paddingHorizontal: 15,
  },
  primaryButton: {
    alignItems: "center",
    backgroundColor: "#7c3aed",
    borderRadius: 12,
    justifyContent: "center",
    marginTop: 16,
    minHeight: 52,
  },
  buttonPressed: { opacity: 0.65 },
  primaryButtonText: { color: "#ffffff", fontSize: 15, fontWeight: "700" },
  switchText: { color: "#c4b5fd", fontSize: 13, marginTop: 20, textAlign: "center" },
  notice: { color: "#f4d28a", fontSize: 13, lineHeight: 19, marginTop: 12 },
  error: { color: "#ff9f9f", fontSize: 13, lineHeight: 19, marginTop: 12 },
  signedInRow: { alignItems: "center", flexDirection: "row", marginBottom: 8 },
  email: { color: "#faf9ff", fontSize: 14, marginTop: 5 },
  signOut: { color: "#c4b5fd", fontSize: 13, padding: 8 },
  resultCard: {
    backgroundColor: "#1b1924",
    borderColor: "#302c3a",
    borderRadius: 22,
    borderWidth: 1,
    marginTop: 18,
    padding: 21,
  },
  resultUrl: { color: "#9c96aa", fontSize: 12, marginTop: 8 },
  resultText: { color: "#eceaf2", fontSize: 15, lineHeight: 25, marginTop: 16 },
  footnote: { color: "#8e8b9a", fontSize: 12, lineHeight: 18, marginTop: 20, textAlign: "center" },
});
