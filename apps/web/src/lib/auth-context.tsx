"use client";

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiClient, ApiClientError, setUnauthorizedHandler } from "@/lib/api-client";
import type { User } from "@/types/api";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  verificationError: string | null;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User | null>;
  retryVerification: () => Promise<User | null>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
  initialUser?: User | null;
  initialLoading?: boolean;
}

export function AuthProvider({
  children,
  initialUser,
  initialLoading,
}: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser ?? null);
  const [isLoading, setIsLoading] = useState<boolean>(
    initialLoading !== undefined ? initialLoading : (initialUser !== undefined ? false : true)
  );
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const router = useRouter();
  const activeSeqRef = useRef<number>(0);

  const refreshUser = useCallback(async (): Promise<User | null> => {
    const seq = ++activeSeqRef.current;
    setIsLoading(true);
    setVerificationError(null);

    try {
      const profile = await apiClient.getMe();
      if (seq !== activeSeqRef.current) return null;
      setUser(profile);
      setVerificationError(null);
      return profile;
    } catch (err) {
      if (seq !== activeSeqRef.current) return null;

      if (err instanceof ApiClientError && err.status === 401) {
        // Confirmed unauthenticated session
        setUser(null);
        setVerificationError(null);
      } else {
        // Recoverable/transient verification error: 503, 500, network offline, timeout
        // DO NOT clear an existing authenticated user session on transient failure
        const msg = err instanceof Error ? err.message : "Authentication service unreachable";
        setVerificationError(msg);
      }
      return null;
    } finally {
      if (seq === activeSeqRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (initialUser === undefined && initialLoading === undefined) {
      refreshUser();
    }
  }, [refreshUser, initialUser, initialLoading]);

  // Wire 401 notification handler from api-client to trigger session refresh
  useEffect(() => {
    setUnauthorizedHandler(() => {
      refreshUser();
    });
    return () => {
      setUnauthorizedHandler(null);
    };
  }, [refreshUser]);

  const login = async (email: string, password: string): Promise<User> => {
    const seq = ++activeSeqRef.current;
    setIsLoading(true);
    setVerificationError(null);
    try {
      const res = await apiClient.login({ email, password });
      if (seq === activeSeqRef.current) {
        setUser(res.user);
        setVerificationError(null);
      }
      return res.user;
    } finally {
      if (seq === activeSeqRef.current) {
        setIsLoading(false);
      }
    }
  };

  const register = async (email: string, password: string): Promise<User> => {
    const newUser = await apiClient.register({ email, password });
    return newUser;
  };

  const logout = async (): Promise<void> => {
    // Clear client state and redirect ONLY after successful logout
    await apiClient.logout();
    activeSeqRef.current++;
    setUser(null);
    setVerificationError(null);
    setIsLoading(false);
    router.push("/login");
  };

  const retryVerification = useCallback(async (): Promise<User | null> => {
    return refreshUser();
  }, [refreshUser]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        verificationError,
        login,
        register,
        logout,
        refreshUser,
        retryVerification,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
