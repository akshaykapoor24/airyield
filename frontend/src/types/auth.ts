export type UserRole =
  | "platform_admin"
  | "super_admin"
  | "company_admin"
  | "operations_user"
  | "finance_user"
  | "approver"
  | "viewer";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
}

export interface Token {
  access_token: string;
  token_type: string;
}
