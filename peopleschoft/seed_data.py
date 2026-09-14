"""Demo organisation: GBI (Global Business Institute), the classic PeopleSoft demo company."""

COMPANIES = [("GBI", "Global Business Institute")]

LOCATIONS = [
    # LOCATION, DESCR, CITY, STATE, COUNTRY
    ("SFHQ", "San Francisco Headquarters", "San Francisco", "CA", "USA"),
    ("NYC01", "New York Office", "New York", "NY", "USA"),
    ("AUS01", "Austin Campus", "Austin", "TX", "USA"),
    ("LON01", "London Office", "London", "", "GBR"),
    ("REMOTE", "Remote / Work from Home", "", "", "USA"),
]

DEPARTMENTS = [
    # DEPTID, DESCR, LOCATION
    ("10000", "Executive Office", "SFHQ"),
    ("11000", "Human Resources", "SFHQ"),
    ("12000", "Finance & Accounting", "NYC01"),
    ("13000", "Engineering", "SFHQ"),
    ("13100", "Platform Engineering", "AUS01"),
    ("14000", "Sales", "NYC01"),
    ("15000", "Marketing", "SFHQ"),
    ("16000", "IT & Security", "AUS01"),
    ("17000", "Customer Support", "REMOTE"),
    ("18000", "EMEA Operations", "LON01"),
]

JOBCODES = [
    # JOBCODE, DESCR, DESCRSHORT, GRADE, JOB_FAMILY, MANAGER_LEVEL
    ("CEO001", "Chief Executive Officer", "CEO", "E1", "EXEC", "1"),
    ("CFO001", "Chief Financial Officer", "CFO", "E2", "EXEC", "2"),
    ("CHRO01", "Chief Human Resources Officer", "CHRO", "E2", "EXEC", "2"),
    ("CTO001", "Chief Technology Officer", "CTO", "E2", "EXEC", "2"),
    ("HRBP01", "HR Business Partner", "HRBP", "P4", "HR", ""),
    ("HRGEN1", "HR Generalist", "HR Gen", "P2", "HR", ""),
    ("ACCT01", "Staff Accountant", "Acct", "P2", "FIN", ""),
    ("FINMGR", "Finance Manager", "Fin Mgr", "M2", "FIN", "5"),
    ("SWE1", "Software Engineer I", "SWE I", "P1", "ENG", ""),
    ("SWE2", "Software Engineer II", "SWE II", "P2", "ENG", ""),
    ("SWE3", "Senior Software Engineer", "Sr SWE", "P3", "ENG", ""),
    ("SWE4", "Staff Software Engineer", "Staff SWE", "P4", "ENG", ""),
    ("ENGMGR", "Engineering Manager", "Eng Mgr", "M2", "ENG", "5"),
    ("DIRENG", "Director of Engineering", "Dir Eng", "M3", "ENG", "4"),
    ("SRE01", "Site Reliability Engineer", "SRE", "P3", "ENG", ""),
    ("SALESR", "Account Executive", "AE", "P2", "SALES", ""),
    ("SALESM", "Sales Manager", "Sales Mgr", "M2", "SALES", "5"),
    ("MKTGSP", "Marketing Specialist", "Mktg Spec", "P2", "MKTG", ""),
    ("MKTGMG", "Marketing Manager", "Mktg Mgr", "M2", "MKTG", "5"),
    ("SYSADM", "Systems Administrator", "SysAdmin", "P2", "IT", ""),
    ("SECENG", "Security Engineer", "Sec Eng", "P3", "IT", ""),
    ("IAMENG", "Identity & Access Engineer", "IAM Eng", "P3", "IT", ""),
    ("ITDIR", "Director of IT", "IT Dir", "M3", "IT", "4"),
    ("CSREP1", "Customer Support Representative", "CS Rep", "P1", "CS", ""),
    ("CSMGR1", "Customer Support Manager", "CS Mgr", "M2", "CS", "5"),
    ("OPSMGR", "Operations Manager", "Ops Mgr", "M2", "OPS", "5"),
    ("CONTR1", "Contractor - Engineering", "Contractor", "C1", "ENG", ""),
    ("INTERN", "Intern", "Intern", "I1", "ENG", ""),
]

# EMPLID, FIRST, LAST, MIDDLE, PREF, SEX, DEPTID, JOBCODE, LOCATION, SUPERVISOR_ID, HIRE_DT, EMPL_STATUS, EMPL_CLASS, REG_TEMP, COMPRATE
EMPLOYEES = [
    ("100001", "Margaret", "Chen", "A", "Maggie", "F", "10000", "CEO001", "SFHQ", "", "2015-01-05", "A", "E", "R", 420000),
    ("100002", "David", "Okafor", "", "", "M", "12000", "CFO001", "NYC01", "100001", "2015-06-15", "A", "E", "R", 310000),
    ("100003", "Priya", "Raman", "", "", "F", "11000", "CHRO01", "SFHQ", "100001", "2016-03-01", "A", "E", "R", 285000),
    ("100004", "Tomas", "Lindqvist", "E", "", "M", "13000", "CTO001", "SFHQ", "100001", "2016-09-12", "A", "E", "R", 330000),
    ("100005", "Aisha", "Mohammed", "", "", "F", "11000", "HRBP01", "SFHQ", "100003", "2018-02-19", "A", "E", "R", 128000),
    ("100006", "Kevin", "Nakamura", "", "Kev", "M", "11000", "HRGEN1", "SFHQ", "100005", "2021-07-06", "A", "E", "R", 84000),
    ("100007", "Laura", "Martinez", "I", "", "F", "12000", "FINMGR", "NYC01", "100002", "2017-11-13", "A", "E", "R", 156000),
    ("100008", "Samuel", "Adeyemi", "", "Sam", "M", "12000", "ACCT01", "NYC01", "100007", "2020-01-27", "A", "E", "R", 78000),
    ("100009", "Elena", "Petrova", "", "", "F", "13000", "DIRENG", "SFHQ", "100004", "2017-04-03", "A", "E", "R", 245000),
    ("100010", "Marcus", "Johnson", "T", "", "M", "13000", "ENGMGR", "SFHQ", "100009", "2018-08-20", "A", "E", "R", 198000),
    ("100011", "Hannah", "Schmidt", "", "", "F", "13000", "SWE3", "SFHQ", "100010", "2019-05-14", "A", "E", "R", 172000),
    ("100012", "Jamal", "Washington", "", "", "M", "13000", "SWE2", "REMOTE", "100010", "2021-10-04", "A", "E", "R", 142000),
    ("100013", "Sofia", "Rossi", "", "", "F", "13000", "SWE1", "SFHQ", "100010", "2023-06-26", "A", "E", "R", 118000),
    ("100014", "Wei", "Zhang", "", "", "M", "13100", "ENGMGR", "AUS01", "100009", "2019-01-07", "A", "E", "R", 195000),
    ("100015", "Olivia", "Brown", "", "Liv", "F", "13100", "SRE01", "AUS01", "100014", "2020-09-08", "A", "E", "R", 168000),
    ("100016", "Daniel", "Kim", "", "", "M", "13100", "SWE4", "REMOTE", "100014", "2018-11-26", "A", "E", "R", 210000),
    ("100017", "Ravi", "Patel", "", "", "M", "13100", "CONTR1", "REMOTE", "100014", "2024-03-18", "A", "C", "T", 95),
    ("100018", "Grace", "O'Neill", "", "", "F", "14000", "SALESM", "NYC01", "100002", "2017-02-06", "A", "E", "R", 175000),
    ("100019", "Carlos", "Mendes", "", "", "M", "14000", "SALESR", "NYC01", "100018", "2022-04-11", "A", "E", "R", 95000),
    ("100020", "Fatima", "Al-Sayed", "", "", "F", "14000", "SALESR", "REMOTE", "100018", "2023-01-09", "L", "E", "R", 92000),
    ("100021", "Noah", "Fischer", "", "", "M", "15000", "MKTGMG", "SFHQ", "100001", "2019-09-23", "A", "E", "R", 150000),
    ("100022", "Isabella", "Nguyen", "", "Bella", "F", "15000", "MKTGSP", "SFHQ", "100021", "2022-08-15", "A", "E", "R", 88000),
    ("100023", "Robert", "Taylor", "J", "Rob", "M", "16000", "ITDIR", "AUS01", "100004", "2016-12-05", "A", "E", "R", 215000),
    ("100024", "Amara", "Diallo", "", "", "F", "16000", "IAMENG", "AUS01", "100023", "2020-03-02", "A", "E", "R", 158000),
    ("100025", "Lucas", "Silva", "", "", "M", "16000", "SECENG", "REMOTE", "100023", "2021-02-22", "A", "E", "R", 162000),
    ("100026", "Emily", "Clark", "", "", "F", "16000", "SYSADM", "AUS01", "100023", "2019-07-15", "T", "E", "R", 98000),
    ("100027", "Mohammed", "Hassan", "", "Mo", "M", "17000", "CSMGR1", "REMOTE", "100003", "2018-05-21", "A", "E", "R", 118000),
    ("100028", "Chloe", "Dubois", "", "", "F", "17000", "CSREP1", "REMOTE", "100027", "2023-11-06", "A", "E", "R", 62000),
    ("100029", "James", "Wright", "", "", "M", "17000", "CSREP1", "REMOTE", "100027", "2024-02-12", "A", "E", "R", 61000),
    ("100030", "Yuki", "Tanaka", "", "", "F", "18000", "OPSMGR", "LON01", "100002", "2020-06-01", "A", "E", "R", 135000),
    ("100031", "Oliver", "Bennett", "", "Ollie", "M", "18000", "CSREP1", "LON01", "100030", "2024-09-02", "A", "E", "R", 48000),
]

# Extra scenario rows applied after the base hires: (EMPLID, EFFDT, ACTION, REASON, overrides)
SCENARIOS = [
    ("100011", "2021-05-01", "PRO", "MER", {"JOBCODE": "SWE3", "COMPRATE": 172000}),   # promoted SWE2 -> SWE3
    ("100012", "2023-03-01", "XFR", "LOC", {"LOCATION": "REMOTE"}),                       # moved to remote
    ("100020", "2025-08-01", "LOA", "PAR", {}),                                          # parental leave (still on leave)
    ("100026", "2025-06-30", "TER", "RES", {}),                                          # resigned
]

TERMINATION_REASONS = {"RES": "Resignation", "INV": "Involuntary", "RET": "Retirement", "DEA": "Death",
                       "EOC": "End of Contract", "RIF": "Reduction in Force", "MUT": "Mutual Agreement"}
