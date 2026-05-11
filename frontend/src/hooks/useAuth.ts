import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { fetchMe, login, logout } from "@/store/slices/authSlice";

export function useAuth() {
  const dispatch = useAppDispatch();
  const router   = useRouter();
  const { user, token, loading, error } = useAppSelector((s) => s.auth);

  useEffect(() => {
    if (token && !user) {
      dispatch(fetchMe());
    }
  }, [token, user, dispatch]);

  const handleLogout = async () => {
    await dispatch(logout());
    router.push("/login");
  };

  return {
    user,
    token,
    loading,
    error,
    isAuthenticated: !!token,
    login: (username: string, password: string) => dispatch(login({ username, password })),
    logout: handleLogout,
  };
}
