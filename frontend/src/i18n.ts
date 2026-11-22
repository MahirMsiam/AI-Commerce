/** UI labels only. Ask and Agent content carry their own language. */
export type Lang = 'en' | 'bn'

const BN: Record<string, string> = {
  Portal: 'পোর্টাল', Dashboard: 'ড্যাশবোর্ড', Ask: 'প্রশ্ন করুন', 'Agent Inbox': 'এজেন্ট ইনবক্স',
  Tasks: 'কাজ', Architecture: 'আর্কিটেকচার', Distributor: 'ডিস্ট্রিবিউটর', Manager: 'ম্যানেজার',
  'Reset demo': 'ডেমো রিসেট', 'Local AI on': 'লোকাল এআই চালু', 'Rules mode': 'রুলস মোড',
  'Prototype · sample data': 'প্রোটোটাইপ · নমুনা ডেটা', Catalogue: 'পণ্য তালিকা', Cart: 'কার্ট',
  'Order history': 'অর্ডারের ইতিহাস', Alerts: 'সতর্কতা', 'Revenue MTD': 'এ মাসের আয়',
  'Orders today': 'আজকের অর্ডার', 'Active distributors': 'সক্রিয় ডিস্ট্রিবিউটর',
  Receivables: 'বকেয়া', Overdue: 'মেয়াদোত্তীর্ণ',
}

export const t = (lang: Lang, s: string) => (lang === 'bn' ? BN[s] ?? s : s)
