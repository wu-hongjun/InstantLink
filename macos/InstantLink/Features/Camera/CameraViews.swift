import SwiftUI

struct CameraView: View {
    @EnvironmentObject var viewModel: ViewModel
    @State private var showFlash = false

    private var showsSimulatedFilmFrame: Bool {
        viewModel.printerModelTag != nil &&
        ((viewModel.cameraState == .viewfinder && viewModel.captureSession != nil) ||
         (viewModel.cameraState == .preview && viewModel.capturedImage != nil))
    }

    private var panelChromeColor: Color {
        showsSimulatedFilmFrame ? .clear : .secondary.opacity(0.18)
    }

    var body: some View {
        ZStack {
            AppPanelBackground(
                chromeColor: panelChromeColor,
                showsChrome: !showsSimulatedFilmFrame
            )

            if viewModel.cameraState == .viewfinder {
                if let session = viewModel.captureSession {
                    let isFront = viewModel.selectedCamera?.position == .front
                    FilmFrameView(filmModel: viewModel.printerModelTag, isRotated: viewModel.filmOrientation == "rotated") {
                        if let ar = viewModel.orientedAspectRatio {
                            CameraPreviewView(session: session, isMirrored: isFront)
                                .scaleEffect(x: viewModel.isHorizontallyFlipped ? -1 : 1, y: 1)
                                .aspectRatio(ar, contentMode: .fill)
                                .overlay {
                                    OverlayCanvasView()
                                }
                                .clipped()
                        } else {
                            CameraPreviewView(session: session, isMirrored: isFront)
                                .scaleEffect(x: viewModel.isHorizontallyFlipped ? -1 : 1, y: 1)
                        }
                    }
                    .padding(4)

                    if let count = viewModel.timerCountdown, count > 0 {
                        Text("\(count)")
                            .font(.system(size: 72, weight: .bold, design: .rounded))
                            .foregroundColor(.white)
                            .shadow(color: .black.opacity(0.5), radius: 8)
                            .transition(.scale.combined(with: .opacity))
                            .animation(.easeInOut(duration: 0.3), value: count)
                    }
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "camera.badge.ellipsis")
                            .font(.largeTitle)
                            .foregroundColor(.secondary)
                        Text(L("No camera available"))
                            .font(.callout)
                            .foregroundColor(.secondary)
                    }
                }
            } else if let image = viewModel.capturedImage {
                FilmFrameView(filmModel: viewModel.printerModelTag, isRotated: viewModel.filmOrientation == "rotated") {
                    if let ar = viewModel.orientedAspectRatio {
                        ExposureAdjustedImageView(image: image, exposureEV: viewModel.exposureEV) { previewImage in
                            previewImage
                                .resizable()
                                .aspectRatio(contentMode: .fill)
                                .scaleEffect(x: viewModel.isHorizontallyFlipped ? -1 : 1, y: 1)
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                                .aspectRatio(ar, contentMode: .fit)
                                .overlay {
                                    OverlayCanvasView()
                                }
                                .clipped()
                        }
                    } else {
                        ExposureAdjustedImageView(image: image, exposureEV: viewModel.exposureEV) { previewImage in
                            previewImage
                                .resizable()
                                .scaleEffect(x: viewModel.isHorizontallyFlipped ? -1 : 1, y: 1)
                                .aspectRatio(contentMode: .fit)
                        }
                    }
                }
                .padding(4)
            }
        }
        .overlay(showFlash ? Color.white.opacity(0.8) : Color.clear)
        .frame(minHeight: 120, maxHeight: .infinity)
        .animation(.easeInOut(duration: 0.22), value: viewModel.cameraState)
        .onChange(of: viewModel.cameraState) { _, newState in
            if newState == .preview {
                showFlash = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    withAnimation(.easeOut(duration: 0.2)) { showFlash = false }
                }
            }
        }
    }
}

struct CameraActionsView: View {
    @EnvironmentObject var viewModel: ViewModel

    private var timerTitle: String {
        switch viewModel.timerMode {
        case 2:
            return "2s"
        case 10:
            return "10s"
        default:
            return L("Off")
        }
    }

    private var isHorizontalOrientation: Bool {
        (viewModel.orientedAspectRatio ?? 1.0) > 1.0
    }

    private var orientationTitle: String {
        isHorizontalOrientation ? L("Horizontal") : L("Vertical")
    }

    private var orientationSymbolName: String {
        isHorizontalOrientation ? "rectangle" : "rectangle.portrait"
    }

    var body: some View {
        VStack(spacing: 10) {
            if viewModel.cameraState == .viewfinder {
                HStack(spacing: 8) {
                    Menu {
                        if viewModel.availableCameras.isEmpty {
                            Text(L("No camera available"))
                        } else {
                            ForEach(viewModel.availableCameras, id: \.uniqueID) { device in
                                Button {
                                    viewModel.switchCamera(to: device)
                                } label: {
                                    if device.uniqueID == viewModel.selectedCamera?.uniqueID {
                                        Label(device.localizedName, systemImage: "checkmark")
                                    } else {
                                        Text(device.localizedName)
                                    }
                                }
                            }
                        }
                    } label: {
                        Label(viewModel.selectedCamera?.localizedName ?? L("Camera"), systemImage: "video")
                    }
                    .buttonStyle(.bordered)
                    .disabled(viewModel.availableCameras.isEmpty)
                    .help(L("Camera"))

                    Menu {
                        Button(L("Off")) { viewModel.timerMode = 0 }
                        Button("2s") { viewModel.timerMode = 2 }
                        Button("10s") { viewModel.timerMode = 10 }
                    } label: {
                        Label(timerTitle, systemImage: "timer")
                    }
                    .buttonStyle(.bordered)
                    .help(L("Timer"))

                    if viewModel.printerAspectRatio != nil {
                        Button {
                            viewModel.filmOrientation = viewModel.filmOrientation == "default" ? "rotated" : "default"
                        } label: {
                            Label(orientationTitle, systemImage: orientationSymbolName)
                        }
                        .buttonStyle(.bordered)
                        .tint(viewModel.filmOrientation == "rotated" ? .accentColor : nil)
                        .help(L("Film Orientation"))

                        Button {
                            viewModel.toggleHorizontalFlip()
                        } label: {
                            Label(L("Flip"), systemImage: "arrow.left.and.right")
                        }
                        .buttonStyle(.bordered)
                        .tint(viewModel.isHorizontallyFlipped ? .accentColor : nil)
                        .help(L("Flip"))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .center)

                if viewModel.timerCountdown != nil {
                    Button {
                        viewModel.cancelTimer()
                    } label: {
                        HStack {
                            Image(systemName: "xmark")
                            Text(L("Cancel"))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .controlSize(.large)
                } else {
                    HStack(spacing: 10) {
                        Button {
                            viewModel.autoPrintAfterCapture = false
                            viewModel.captureWithTimer()
                        } label: {
                            HStack {
                                Image(systemName: "camera.shutter.button")
                                Text(L("Capture"))
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .controlSize(.large)
                        .disabled(viewModel.captureSession == nil)

                        Button {
                            viewModel.autoPrintAfterCapture = true
                            viewModel.captureWithTimer()
                        } label: {
                            HStack {
                                Image(systemName: "printer.fill")
                                Text(L("Capture & Print"))
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .disabled(viewModel.captureSession == nil || !viewModel.isConnected || viewModel.isPrinting)
                    }
                }
            } else {
                HStack(spacing: 10) {
                    Button {
                        viewModel.retakePhoto()
                    } label: {
                        HStack {
                            Image(systemName: "arrow.counterclockwise")
                            Text(L("Retake"))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .controlSize(.large)

                    Button {
                        if viewModel.commitCapture() {
                            viewModel.showImageEditor = true
                        }
                    } label: {
                        HStack {
                            Image(systemName: "slider.horizontal.3")
                            Text(L("Edit"))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .tint(.orange)
                    .controlSize(.large)

                    Button {
                        if viewModel.commitCapture() {
                            Task { await viewModel.printSelectedImage() }
                        }
                    } label: {
                        HStack {
                            Image(systemName: "printer.fill")
                            Text(L("Print"))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(!viewModel.isConnected || viewModel.isPrinting)
                }
            }
        }
        .onAppear {
            if viewModel.captureMode == .camera {
                viewModel.discoverCameras(ensureSession: true)
            }
        }
    }
}
