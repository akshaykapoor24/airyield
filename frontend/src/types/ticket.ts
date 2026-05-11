export interface Ticket {
  id: number;
  ticket_number: string;
  pnr: string | null;
  airline_id: number;
  booking_class: string;
  travel_date: string;
  origin_code: string;
  destination_code: string;
  base_fare: number;
  total_fare: number;
  currency: string;
  matched_deal_id: number | null;
  is_manually_matched: boolean;
}
