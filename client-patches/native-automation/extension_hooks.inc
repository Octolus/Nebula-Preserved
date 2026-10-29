// Stable no-op extension seam. Future reviewed modules replace only the
// bounded marker bodies through the integration composer; existing economy
// and social source blocks remain byte-identical.
bool additional_module_pending() noexcept {
    /* INTEGRATION_PENDING_EXTENSIONS */
    return false;
}
void service_additional_modules(void*,uint64_t) noexcept {
    /* INTEGRATION_SERVICE_EXTENSIONS */
}
void add_additional_snapshots(Json&) noexcept {
    /* INTEGRATION_SNAPSHOT_EXTENSIONS */
}
