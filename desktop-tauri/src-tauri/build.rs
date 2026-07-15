fn main() {
    // Bug-fix: Add error handling to the build script.
    // If tauri_build fails, print the error and exit with a non-zero code
    // so that CI/packaging tooling knows something went wrong.
    if let Err(e) = std::panic::catch_unwind(|| {
        tauri_build::build()
    }) {
        eprintln!("[build.rs] tauri_build::build() panicked: {:?}", e);
        std::process::exit(1);
    }
}
