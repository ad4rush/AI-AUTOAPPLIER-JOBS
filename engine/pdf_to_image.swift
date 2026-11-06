import Foundation
import PDFKit
import Cocoa

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("Usage: swift pdf_to_image.swift <input.pdf> <output.png> [scale]")
    exit(1)
}

let inputPath = args[1]
let outputPath = args[2]
let scale: CGFloat = args.count >= 4 ? CGFloat(Double(args[3]) ?? 2.5) : 2.5

let pdfUrl = URL(fileURLWithPath: inputPath)
guard let pdfDoc = PDFDocument(url: pdfUrl), let page = pdfDoc.page(at: 0) else {
    print("Failed to load PDF page from \(inputPath)")
    exit(1)
}

let pageRect = page.bounds(for: .mediaBox)
let targetSize = NSSize(width: pageRect.width * scale, height: pageRect.height * scale)

let image = NSImage(size: targetSize)
image.lockFocus()

guard let context = NSGraphicsContext.current?.cgContext else {
    print("Failed to get CGContext")
    exit(1)
}

// Fill background with solid OPAQUE WHITE (Alpha = 1.0)
context.setFillColor(CGColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0))
context.fill(CGRect(origin: .zero, size: targetSize))

// Scale and render PDF page
context.scaleBy(x: scale, y: scale)
page.draw(with: .mediaBox, to: context)

image.unlockFocus()

guard let tiffData = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiffData),
      let pngData = bitmap.representation(using: .png, properties: [:]) else {
    print("Failed to convert image to PNG")
    exit(1)
}

do {
    try pngData.write(to: URL(fileURLWithPath: outputPath))
    print("Successfully rendered PDF to white-background PNG at \(outputPath)")
} catch {
    print("Error saving PNG: \(error)")
    exit(1)
}
