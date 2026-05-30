import SwiftUI

/// Reusable section card for the Bridge Settings tab.
///
/// Mirrors ``BridgeCard`` (defined in `BridgeOverviewView.swift`) but
/// adds an optional footer slot for inline error / hint copy.
struct BridgeSettingsSection<Content: View, Footer: View>: View {
    let title: String
    let content: () -> Content
    let footer: () -> Footer

    init(
        title: String,
        @ViewBuilder content: @escaping () -> Content,
        @ViewBuilder footer: @escaping () -> Footer
    ) {
        self.title = title
        self.content = content
        self.footer = footer
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.headline)
            content()
            let footerView = footer()
            // A naked Conditional view satisfies the generic Footer requirement;
            // we only render the footer slot when it produces visible content.
            footerView
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.secondary.opacity(0.08))
        )
    }
}

extension BridgeSettingsSection where Footer == EmptyView {
    init(
        title: String,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.content = content
        self.footer = { EmptyView() }
    }
}

/// Inline error / hint row used as a section footer.
struct BridgeSettingsHint: View {
    let message: String
    let isError: Bool

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: isError ? "exclamationmark.triangle.fill" : "info.circle")
                .font(.caption)
            Text(message)
                .font(.caption)
        }
        .foregroundColor(isError ? .red : .secondary)
    }
}
