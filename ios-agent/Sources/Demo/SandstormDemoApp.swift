import SwiftUI

@main
struct SandstormDemoApp: App {
    var body: some Scene {
        WindowGroup {
            LoginView()
        }
    }
}

/// A deliberately tiny app under test used to validate the agent end to end.
struct LoginView: View {
    @State private var username = ""
    @State private var password = ""
    @State private var isLoggedIn = false
    @State private var showsError = false

    var body: some View {
        NavigationStack {
            if isLoggedIn {
                VStack(spacing: 16) {
                    Text("Welcome \(username)")
                        .font(.title2)
                        .accessibilityIdentifier("welcome_message")
                    Button("Log out") {
                        isLoggedIn = false
                        username = ""
                        password = ""
                    }
                    .accessibilityIdentifier("logout_button")
                }
                .padding()
            } else {
                Form {
                    Section("Credentials") {
                        TextField("Email", text: $username)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .accessibilityIdentifier("username")
                        SecureField("Password", text: $password)
                            .accessibilityIdentifier("password")
                    }
                    Section {
                        Button("Login") {
                            if username.isEmpty || password.isEmpty {
                                showsError = true
                            } else {
                                isLoggedIn = true
                            }
                        }
                        .accessibilityIdentifier("login_button")
                    }
                }
                .navigationTitle("Sandstorm Demo")
                .alert("Missing credentials", isPresented: $showsError) {
                    Button("OK", role: .cancel) {}
                }
            }
        }
    }
}
