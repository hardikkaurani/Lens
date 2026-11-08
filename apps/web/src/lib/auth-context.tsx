"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { User } from "@/types/api";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User | null>;
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
  const router = useRouter();

  const refreshUser = useCallback(async (): Promise<User | null> => {
    try {
      const profile = await apiClient.getMe();
      setUser(profile);
      return profile;
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 401) {
        setUser(null);
      }
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialUser === undefined && initialLoading === undefined) {
      refreshUser();
    }
  }, [refreshUser, initialUser, initialLoading]);

  const login = async (email: string, password: string): Promise<User> => {
    const res = await apiClient.login({ email, password });
    setUser(res.user);
    return res.user;
  };

  const register = async (email: string, password: string): Promise<User> => {
    const newUser = await apiClient.register({ email, password });
    return newUser;
  };

  const logout = async (): Promise<void> => {
    try {
      await apiClient.logout();
    } finally {
      setUser(null);
      router.push("/login");
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        refreshUser,
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
