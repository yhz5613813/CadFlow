#include "io/exchange.h"

#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#ifdef CADFLOW_WITH_STEP
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#endif
#include <StlAPI_Writer.hxx>
#include <TopAbs.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#endif

namespace cadflow::io {

core::ShapeId import_step(core::Session& session, const std::string& path) {
    if (path.empty()) {
        throw std::invalid_argument("STEP path is empty");
    }
#if defined(CADFLOW_WITH_OCCT) && defined(CADFLOW_WITH_STEP)
    STEPControl_Reader reader;
    if (reader.ReadFile(path.c_str()) != IFSelect_RetDone || reader.TransferRoots() <= 0) {
        throw std::runtime_error("OCCT STEP import failed");
    }
    core::Shape output {core::Shape::Kind::Imported};
    output.native = reader.OneShape();
    if (output.native.IsNull()) {
        throw std::runtime_error("OCCT STEP import returned a null shape");
    }
    return core::store(session, std::move(output));
#else
    (void)session;
    throw std::runtime_error("STEP import requires the OCCT backend");
#endif
}

void export_step(
    const core::Session& session, core::ShapeId id, const std::string& path) {
    if (path.empty()) {
        throw std::invalid_argument("STEP path is empty");
    }
#if defined(CADFLOW_WITH_OCCT) && defined(CADFLOW_WITH_STEP)
    STEPControl_Writer writer;
    if (writer.Transfer(core::get_shape(session, id).native, STEPControl_AsIs)
            != IFSelect_RetDone
        || writer.Write(path.c_str()) != IFSelect_RetDone) {
        throw std::runtime_error("OCCT STEP export failed");
    }
#else
    (void)session;
    (void)id;
    throw std::runtime_error("STEP export requires the OCCT backend");
#endif
}

void export_stl(
    const core::Session& session, core::ShapeId id, const std::string& path, bool binary) {
    if (path.empty()) {
        throw std::invalid_argument("STL path is empty");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    BRepMesh_IncrementalMesh mesher(shape, 0.1, false, 0.5, true);
    mesher.Perform();
    if (!mesher.IsDone()) {
        throw std::runtime_error("OCCT STL tessellation failed");
    }
    StlAPI_Writer writer;
    writer.ASCIIMode() = !binary;
    if (!writer.Write(shape, path.c_str())) {
        throw std::runtime_error("OCCT STL export failed");
    }
#else
    (void)session;
    (void)id;
    (void)binary;
    throw std::runtime_error("STL export requires the OCCT backend");
#endif
}

std::string mesh_json(
    const core::Session& session, core::ShapeId id, double deflection) {
    if (!(deflection > 0.0)) {
        throw std::invalid_argument("mesh deflection must be positive");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    BRepMesh_IncrementalMesh mesher(shape, deflection, false, 0.5, true);
    std::vector<double> vertices;
    std::vector<int> triangles;
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        const TopoDS_Face face = TopoDS::Face(explorer.Current());
        TopLoc_Location location;
        const Handle(Poly_Triangulation) triangulation =
            BRep_Tool::Triangulation(face, location);
        if (triangulation.IsNull()) {
            continue;
        }
        const int base = static_cast<int>(vertices.size() / 3);
        for (int index = 1; index <= triangulation->NbNodes(); ++index) {
            const gp_Pnt point =
                triangulation->Node(index).Transformed(location.Transformation());
            vertices.insert(vertices.end(), {point.X(), point.Y(), point.Z()});
        }
        for (int index = 1; index <= triangulation->NbTriangles(); ++index) {
            int first;
            int second;
            int third;
            triangulation->Triangle(index).Get(first, second, third);
            triangles.insert(
                triangles.end(), {base + first - 1, base + second - 1, base + third - 1});
        }
    }
    std::ostringstream output;
    output << std::setprecision(17) << "{\"vertices\":[";
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        if (index) {
            output << ',';
        }
        output << vertices[index];
    }
    output << "],\"triangles\":[";
    for (std::size_t index = 0; index < triangles.size(); ++index) {
        if (index) {
            output << ',';
        }
        output << triangles[index];
    }
    output << "]}";
    return output.str();
#else
    (void)session;
    (void)id;
    throw std::runtime_error("mesh export requires the OCCT backend");
#endif
}

}  // namespace cadflow::io
