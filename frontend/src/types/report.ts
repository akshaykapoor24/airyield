export interface IncomeRecord {
  id: number;
  ticket_id: number;
  deal_id: number;
  base_fare: number;
  commission_amount: number;
  override_amount: number;
  incentive_amount: number;
  total_income: number;
  currency: string;
  is_manual_override: boolean;
  is_approved: boolean;
  calculated_at: string;
}

export interface DashboardStats {
  total_income: number;
  approved_income: number;
  total_tickets: number;
}

export interface AirlineReport {
  airline: string;
  iata_code: string;
  total_income: number;
}

export interface RouteReport {
  route: string;
  total_income: number;
  ticket_count: number;
}
