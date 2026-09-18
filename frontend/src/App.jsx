import { useCallback, useEffect, useMemo, useState } from "react";

import {
  API_BASE_URL,
  checkHealth,
  getDistricts,
  getStates,
  getStats,
  getSupplier,
  getSuppliers,
} from "./services/api";

import {
  Activity,
  AlertCircle,
  Building2,
  ChevronLeft,
  ChevronRight,
  Database,
  ExternalLink,
  Filter,
  MapPin,
  RefreshCw,
  Search,
  Server,
  X,
} from "lucide-react";

import "./App.css";


function formatNumber(value) {
  return new Intl.NumberFormat("en-IN").format(
    Number(value || 0)
  );
}


function formatActivities(activities) {
  if (!activities) {
    return [];
  }

  if (Array.isArray(activities)) {
    return activities;
  }

  if (typeof activities === "string") {
    try {
      const parsed = JSON.parse(activities);

      if (Array.isArray(parsed)) {
        return parsed;
      }
    } catch {
      return [
        {
          Description: activities,
        },
      ];
    }
  }

  return [];
}


function StatCard({ icon, label, value, loading }) {
  return (
    <div className="stat-card">
      <div className="stat-icon">
        {icon}
      </div>

      <div>
        <div className="stat-label">
          {label}
        </div>

        <div className="stat-value">
          {loading ? "..." : formatNumber(value)}
        </div>
      </div>
    </div>
  );
}


function SupplierModal({
  supplier,
  loading,
  onClose,
}) {
  if (!supplier && !loading) {
    return null;
  }

  const activities = supplier
    ? formatActivities(supplier.activities)
    : [];

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal">
        <div className="modal-header">
          <div>
            <div className="modal-eyebrow">
              SUPPLIER PROFILE
            </div>

            <h2>
              {loading
                ? "Loading supplier..."
                : supplier?.enterprise_name || "Supplier"}
            </h2>
          </div>

          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        {loading ? (
          <div className="modal-loading">
            <div className="spinner" />
            <span>Loading supplier details...</span>
          </div>
        ) : (
          <div className="modal-body">
            <div className="detail-grid">

              <div className="detail-item detail-wide">
                <span>Enterprise name</span>
                <strong>
                  {supplier.enterprise_name || "—"}
                </strong>
              </div>

              <div className="detail-item">
                <span>State</span>
                <strong>
                  {supplier.state || "—"}
                </strong>
              </div>

              <div className="detail-item">
                <span>District</span>
                <strong>
                  {supplier.district || "—"}
                </strong>
              </div>

              <div className="detail-item">
                <span>PIN code</span>
                <strong>
                  {supplier.pincode || "—"}
                </strong>
              </div>

              <div className="detail-item">
                <span>Registration date</span>
                <strong>
                  {supplier.registration_date || "—"}
                </strong>
              </div>

              <div className="detail-item detail-wide">
                <span>Communication address</span>
                <strong>
                  {supplier.communication_address || "—"}
                </strong>
              </div>

            </div>

            <div className="activities-section">
              <div className="section-heading">
                <Activity size={18} />
                <span>Business activities</span>
              </div>

              {activities.length > 0 ? (
                <div className="activity-list">
                  {activities.map((activity, index) => (
                    <div
                      className="activity-item"
                      key={`${activity.NIC5DigitId || "activity"}-${index}`}
                    >
                      {activity.NIC5DigitId && (
                        <span className="activity-code">
                          NIC {activity.NIC5DigitId}
                        </span>
                      )}

                      <span>
                        {activity.Description ||
                          activity.description ||
                          String(activity)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-inline">
                  No activity information available.
                </div>
              )}
            </div>

            <div className="source-section">
              <div className="section-heading">
                <Database size={18} />
                <span>Source information</span>
              </div>

              <div className="source-grid">
                <div>
                  <span>Source file</span>
                  <strong>
                    {supplier.source_file || "—"}
                  </strong>
                </div>

                <div>
                  <span>Batch ID</span>
                  <strong>
                    {supplier.batch_id || "—"}
                  </strong>
                </div>

                <div>
                  <span>Source state</span>
                  <strong>
                    {supplier.source_state || "—"}
                  </strong>
                </div>

                <div>
                  <span>LG state code</span>
                  <strong>
                    {supplier.lg_st_code || "—"}
                  </strong>
                </div>

                <div>
                  <span>LG district code</span>
                  <strong>
                    {supplier.lg_dt_code || "—"}
                  </strong>
                </div>

                <div>
                  <span>Source offset</span>
                  <strong>
                    {supplier.source_offset ?? "—"}
                  </strong>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


function App() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const [district, setDistrict] = useState("");
  const [pincode, setPincode] = useState("");

  const [states, setStates] = useState([]);
  const [districts, setDistricts] = useState([]);

  const [suppliers, setSuppliers] = useState([]);
  const [stats, setStats] = useState({
    total: 0,
    states: 0,
    districts: 0,
  });

  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [apiOnline, setApiOnline] = useState(false);
  const [error, setError] = useState("");

  const [selectedSupplier, setSelectedSupplier] =
    useState(null);

  const [detailLoading, setDetailLoading] =
    useState(false);

  const hasFilters = useMemo(
    () =>
      Boolean(
        search.trim() ||
        state ||
        district ||
        pincode.trim()
      ),
    [
      search,
      state,
      district,
      pincode,
    ]
  );


  const loadStats = useCallback(async () => {
    setStatsLoading(true);

    try {
      const data = await getStats();

      setStats(data);
      setApiOnline(true);
    } catch {
      setApiOnline(false);
    } finally {
      setStatsLoading(false);
    }
  }, []);


  const loadStates = useCallback(async () => {
    try {
      const response = await getStates();

      setStates(response.data || []);
      setApiOnline(true);
    } catch {
      setStates([]);
      setApiOnline(false);
    }
  }, []);


  const loadDistricts = useCallback(
    async (selectedState) => {
      try {
        const response =
          await getDistricts(selectedState);

        setDistricts(response.data || []);
        setApiOnline(true);
      } catch {
        setDistricts([]);
        setApiOnline(false);
      }
    },
    []
  );


  const loadSuppliers = useCallback(
    async (currentPage = page) => {
      setLoading(true);
      setError("");

      try {
        const response = await getSuppliers({
          search,
          state,
          district,
          pincode,
          page: currentPage,
          page_size: pageSize,
        });

        setSuppliers(response.data || []);
        setTotal(response.total || 0);
        setTotalPages(
          Math.max(response.total_pages || 1, 1)
        );
        setPage(response.page || currentPage);
        setApiOnline(true);
      } catch (requestError) {
        setSuppliers([]);
        setTotal(0);
        setTotalPages(1);
        setError(
          requestError?.message ||
            "Failed to fetch suppliers."
        );
        setApiOnline(false);
      } finally {
        setLoading(false);
      }
    },
    [
      search,
      state,
      district,
      pincode,
      page,
      pageSize,
    ]
  );


  useEffect(() => {
    loadStats();
    loadStates();
    loadSuppliers(1);
  }, []);


  useEffect(() => {
    loadDistricts(state);

    setDistrict("");
    setPage(1);
  }, [state, loadDistricts]);


  async function handleRefresh() {
    setRefreshing(true);

    await Promise.all([
      loadStats(),
      loadStates(),
      loadDistricts(state),
      loadSuppliers(page),
    ]);

    setRefreshing(false);
  }


  function handleSearch(event) {
    event.preventDefault();

    setPage(1);
    loadSuppliers(1);
  }


  function handleClear() {
    setSearch("");
    setState("");
    setDistrict("");
    setPincode("");
    setPage(1);

    setTimeout(() => {
      loadSuppliers(1);
    }, 0);
  }


  async function handleViewSupplier(id) {
    setDetailLoading(true);
    setSelectedSupplier(null);

    try {
      const supplier = await getSupplier(id);

      setSelectedSupplier(supplier);
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Failed to load supplier details."
      );
    } finally {
      setDetailLoading(false);
    }
  }


  function handlePrevious() {
    if (page > 1) {
      const nextPage = page - 1;

      setPage(nextPage);
      loadSuppliers(nextPage);
    }
  }


  function handleNext() {
    if (page < totalPages) {
      const nextPage = page + 1;

      setPage(nextPage);
      loadSuppliers(nextPage);
    }
  }


  return (
    <div className="app">

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Building2 size={22} />
          </div>

          <div>
            <div className="brand-name">
              Supplier Explorer
            </div>

            <div className="brand-subtitle">
              Udyam MSME Directory
            </div>
          </div>
        </div>

        <div
          className={`api-status ${
            apiOnline ? "online" : "offline"
          }`}
        >
          <span className="status-dot" />
          {apiOnline
            ? "API Connected"
            : "API Offline"}
        </div>
      </header>


      <main>

        <section className="hero">
          <div className="hero-content">

            <div className="eyebrow">
              SUPPLIER DISCOVERY
            </div>

            <h1>
              Explore verified
              <br />
              <span>Udyam suppliers.</span>
            </h1>

            <p>
              Search and discover MSME suppliers using
              real-time data from the Udyam Snowflake
              database.
            </p>

            <div className="hero-meta">
              <span>
                <Server size={15} />
                FastAPI
              </span>

              <span>
                <Database size={15} />
                Snowflake
              </span>

              <span>
                <Building2 size={15} />
                MSME Directory
              </span>
            </div>
          </div>
        </section>


        <section className="content">

          <div className="stats-grid">

            <StatCard
              icon={<Building2 size={21} />}
              label="Total Suppliers"
              value={stats.total}
              loading={statsLoading}
            />

            <StatCard
              icon={<MapPin size={21} />}
              label="States"
              value={stats.states}
              loading={statsLoading}
            />

            <StatCard
              icon={<MapPin size={21} />}
              label="Districts"
              value={stats.districts}
              loading={statsLoading}
            />

          </div>


          <section className="search-panel">

            <div className="panel-heading">
              <div>
                <h2>Search suppliers</h2>
                <p>
                  Find suppliers by name, location or
                  pincode.
                </p>
              </div>

              <Filter size={20} />
            </div>


            <form
              className="search-form"
              onSubmit={handleSearch}
            >

              <div className="search-input-wrap">
                <Search size={19} />

                <input
                  type="text"
                  placeholder="Search enterprise, district, state or address..."
                  value={search}
                  onChange={(event) =>
                    setSearch(event.target.value)
                  }
                />
              </div>

              <div className="filter-row">

                <select
                  value={state}
                  onChange={(event) => {
                    setState(event.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">
                    All States
                  </option>

                  {states.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>


                <select
                  value={district}
                  onChange={(event) => {
                    setDistrict(event.target.value);
                    setPage(1);
                  }}
                  disabled={!state && districts.length === 0}
                >
                  <option value="">
                    All Districts
                  </option>

                  {districts.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>


                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={10}
                  placeholder="PIN code"
                  value={pincode}
                  onChange={(event) => {
                    setPincode(
                      event.target.value.replace(
                        /\D/g,
                        ""
                      )
                    );
                    setPage(1);
                  }}
                />


                <button
                  type="submit"
                  className="primary-button"
                >
                  <Search size={17} />
                  Search
                </button>


                <button
                  type="button"
                  className="secondary-button"
                  onClick={handleClear}
                  disabled={!hasFilters}
                >
                  Clear
                </button>


                <button
                  type="button"
                  className="refresh-button"
                  onClick={handleRefresh}
                  disabled={refreshing}
                  title="Refresh data"
                >
                  <RefreshCw
                    size={18}
                    className={
                      refreshing
                        ? "spin"
                        : ""
                    }
                  />
                </button>

              </div>

            </form>

          </section>


          {error && (
            <div className="error-banner">
              <AlertCircle size={20} />

              <div>
                <strong>
                  Unable to load data
                </strong>

                <span>
                  {error}
                </span>
              </div>

              <button
                className="error-close"
                onClick={() => setError("")}
              >
                <X size={17} />
              </button>
            </div>
          )}


          <section className="results-panel">

            <div className="results-header">

              <div>
                <div className="results-title">
                  RESULTS
                </div>

                <h2>
                  {loading
                    ? "Loading suppliers..."
                    : `${formatNumber(total)} supplier${
                        total === 1 ? "" : "s"
                      } found`}
                </h2>
              </div>

              {!loading && total > 0 && (
                <div className="pagination-info">
                  Page {page} of {totalPages}
                </div>
              )}

            </div>


            <div className="table-wrapper">

              <table>

                <thead>
                  <tr>
                    <th>Supplier</th>
                    <th>State</th>
                    <th>District</th>
                    <th>PIN Code</th>
                    <th>Registration</th>
                    <th />
                  </tr>
                </thead>

                <tbody>

                  {loading ? (
                    Array.from({
                      length: 6,
                    }).map((_, index) => (
                      <tr key={index}>
                        <td colSpan="6">
                          <div className="skeleton-row">
                            <div />
                            <div />
                            <div />
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : suppliers.length > 0 ? (
                    suppliers.map((supplier) => (
                      <tr key={supplier.id}>

                        <td>
                          <div className="supplier-cell">
                            <div className="supplier-avatar">
                              <Building2 size={17} />
                            </div>

                            <div>
                              <strong>
                                {supplier.enterprise_name ||
                                  "Unnamed supplier"}
                              </strong>

                              <span>
                                {supplier.communication_address ||
                                  "No address available"}
                              </span>
                            </div>
                          </div>
                        </td>

                        <td>
                          {supplier.state || "—"}
                        </td>

                        <td>
                          {supplier.district || "—"}
                        </td>

                        <td>
                          <span className="pin-badge">
                            {supplier.pincode || "—"}
                          </span>
                        </td>

                        <td>
                          {supplier.registration_date ||
                            "—"}
                        </td>

                        <td>
                          <button
                            className="view-button"
                            onClick={() =>
                              handleViewSupplier(
                                supplier.id
                              )
                            }
                          >
                            View
                            <ExternalLink size={14} />
                          </button>
                        </td>

                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td
                        colSpan="6"
                        className="empty-state"
                      >
                        <div className="empty-icon">
                          <Search size={25} />
                        </div>

                        <strong>
                          No suppliers found
                        </strong>

                        <span>
                          Try changing your search or
                          filters.
                        </span>

                        {hasFilters && (
                          <button
                            className="secondary-button"
                            onClick={handleClear}
                          >
                            Clear filters
                          </button>
                        )}
                      </td>
                    </tr>
                  )}

                </tbody>

              </table>

            </div>


            <div className="pagination">

              <button
                className="pagination-button"
                onClick={handlePrevious}
                disabled={
                  loading || page <= 1
                }
              >
                <ChevronLeft size={17} />
                Previous
              </button>

              <div className="page-number">
                {page}
                <span>/</span>
                {totalPages}
              </div>

              <button
                className="pagination-button"
                onClick={handleNext}
                disabled={
                  loading ||
                  page >= totalPages
                }
              >
                Next
                <ChevronRight size={17} />
              </button>

            </div>

          </section>

        </section>

      </main>


      <footer>
        <div>
          <strong>
            Supplier Explorer
          </strong>

          <span>
            FastAPI · Snowflake · React
          </span>
        </div>

        <a
          href={API_BASE_URL}
          target="_blank"
          rel="noreferrer"
        >
          API
          <ExternalLink size={13} />
        </a>
      </footer>


      <SupplierModal
        supplier={selectedSupplier}
        loading={detailLoading}
        onClose={() => {
          setSelectedSupplier(null);
          setDetailLoading(false);
        }}
      />

    </div>
  );
}

export default App;